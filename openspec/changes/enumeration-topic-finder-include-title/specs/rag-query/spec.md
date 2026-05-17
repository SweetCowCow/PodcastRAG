## MODIFIED Requirements

### Requirement: Chat endpoint answers with citations using Tier 2 RAG

The backend SHALL expose `POST /shows/{show_id}/query` guarded by `require_authenticated_user` and atomic quota decrement (see user-quota). The endpoint SHALL execute the Tier 2 RAG pipeline: (1) if the request includes a non-empty `messages` history, rewrite the question to a standalone form using the configured rewrite model; (2) call the `entity_extraction` AI step (see query-entity-extraction capability) to extract `{date_range, guests, topics}` from the rewritten question — failure to extract SHALL fail-open with empty entities, NOT raise 5xx; (3) embed the rewritten question AND jieba-tokenise it; (4) perform retrieval combining semantic + three-pool lexical RRF across `transcript_chunks`, `episode_description_chunks`, AND `episodes.title_tsvector`, applying any extracted entity hard filters (`episodes.guests @> :guest_list` and/or `episodes.published_at BETWEEN :start AND :end`); (5) if the extracted entities indicate an enumeration query (non-empty guests OR non-empty date_range OR non-empty topics OR question matches enumeration rule pattern), populate `enumeration_episodes` field listing all matched episodes (not limited to top-K chunks) AND populate `enumeration_total` with the full count; (6) when `enumeration_episodes` is non-empty, the answer prompt SHALL include a structured grounding block listing up to the first 30 enumeration episodes (with title, published_at, and guests) BEFORE the chunk citations block, so the answer model can ground its prose count on the enumeration list rather than the top-K chunk subset; (7) generate an answer using the configured answer model with the retrieved chunks AND the grounding block as input, requesting structured JSON output containing `answer` and `used_chunk_ids`; (8) return the answer together with only the citation chunks referenced in `used_chunk_ids`, plus `enumeration_episodes` and `enumeration_total` when applicable. Description-source citations SHALL be presented to the answer model with a clear marker (e.g. `desc:<episode_id>`) distinguishing them from transcript citations (`ep:<episode_id>@<start_time>`). If JSON parsing of the model output fails, the endpoint SHALL fall back to returning the salvaged answer string (via the malformed-JSON salvage regex from R3.3) with all retrieved chunks as `citations`. This endpoint SHALL NOT accept anonymous callers and SHALL NOT consult the IP rate limit.

#### Scenario: Hybrid retrieval result feeds answer prompt

- **WHEN** a chat-mode query is issued and hybrid retrieval returns 5 transcript chunks and 3 description chunks
- **THEN** the answer prompt SHALL list all 8 results, each prefixed with `ep:<episode_id>@<start_time>` for transcripts or `desc:<episode_id>` for descriptions
- **AND** the model is permitted to cite either form in `used_chunk_ids`

#### Scenario: Entity extraction fails-open without breaking retrieval

- **WHEN** chat query is processed and the `entity_extraction` step raises an exception or returns invalid JSON
- **THEN** the endpoint SHALL log a warning, treat extracted entities as empty, and continue retrieval without metadata filter
- **AND** the response SHALL be HTTP 200 (not 5xx) with normal `answer` + `citations`
- **AND** `enumeration_episodes` SHALL be `null` AND `enumeration_total` SHALL be `null`

#### Scenario: Topic-only query triggers enumeration

- **GIVEN** a chat query `"歌單那幾集"` whose entity extractor returns `{guests: [], date_range: null, topics: ["歌單"]}`
- **WHEN** the chat endpoint processes the query
- **THEN** `enumeration_episodes` SHALL contain all episodes whose `episodes.title_tsvector @@ to_tsquery('simple', '歌單')` matches, OR whose `episode_description_chunks.text_tsvector @@ to_tsquery('simple', '歌單')` matches (set union by `episodes.id`)
- **AND** `enumeration_total` SHALL equal the length of that distinct list
- **AND** the response SHALL NOT fall back to "list every episode of the show"

#### Scenario: Guest filter narrows retrieval AND grounds answer

- **WHEN** chat query `"楊大正是哪幾集的來賓？"` extracts `guests = ["楊大正"]` AND `episodes.guests @> '["楊大正"]'` matches exactly 2 episodes
- **THEN** `enumeration_episodes` SHALL contain those 2 episodes AND `enumeration_total` SHALL be 2
- **AND** the answer prompt SHALL include a grounding block prefixed `## 相關集數清單（共 2 集）` listing those 2 episodes BEFORE the chunk citations
- **AND** the answer text SHALL NOT claim a count different from 2 (e.g. SHALL NOT say "1 集" or "3 集")

##### Example: structured grounding block format

- **GIVEN** enumeration_episodes contains 2 entries: EP143 (2026-04-29, ft. 馬世芳) and EP140 (2026-04-15)
- **WHEN** the answer prompt is constructed
- **THEN** the prompt SHALL contain a block matching this shape (literal first line, then numbered list of episodes):

```

## 相關集數清單（共 2 集）
這個問題的搜尋結果鎖定以下集數，作為你回答的依據：
1. EP143「從餐廳請客到自家廚房」(2026-04-29, ft. 馬世芳)
2. EP140「高雄美食第二彈」(2026-04-15)

```

### Requirement: Topic-driven enumeration finder pre-tokenises LLM phrases with jieba

`find_episodes_by_topic(db, show_id, topic_terms)` SHALL jieba-tokenise each input `topic_terms` entry before constructing the `to_tsquery('simple', :tsquery_text)` argument. Each per-term jieba token of length ≥ 2 that is NOT in `TOPIC_STOPWORDS` SHALL contribute to the tsquery; per-term tokens are deduplicated across all input terms (first occurrence wins). When jieba produces zero useful tokens for a given term (e.g. the term is all stopwords or all single-char particles), the raw term SHALL be retained as a fallback so the LLM's signal is not silently dropped.

The constructed tsquery SHALL be matched against BOTH `episodes.title_tsvector` AND `episode_description_chunks.text_tsvector`. An episode SHALL be returned if its `title_tsvector` matches the tsquery OR if at least one of its `episode_description_chunks.text_tsvector` rows matches. The returned `list[EpisodeRef]` SHALL be distinct by `episodes.id` (no episode appears twice when both pools match) and ordered by `published_at DESC NULLS LAST`.

Rationale: `episode_description_chunks.text_tsvector` is built from a jieba-tokenised stream (per R3.1 `description_indexer.py`) and `episodes.title_tsvector` is built from the same jieba tokenizer (per R3.3 Phase 8 `sync._title_tsv_expr`), so the lexemes stored are per-word tokens like `高雄` and `美食`. Postgres `simple` analyzer does NOT segment CJK, so passing a multi-character LLM-extracted phrase like `"高雄美食"` directly to `to_tsquery('simple', '高雄美食')` matches ZERO rows even when descriptions clearly contain those topics — the corpus stores `高雄` and `美食` as separate lexemes. Pre-tokenising at the finder level closes the impedance mismatch. Including the title pool alongside description chunks closes a separate gap (observed in 2026-05-17 q25 audit): 6 episodes (EP19 / EP84 / EP87 / EP89 / EP96 / EP108) whose titles contain `歌單` but whose descriptions do not — these were silently missing from enumeration results when the finder only consulted description chunks.

#### Scenario: Multi-character LLM topic phrase is split into component words

- **GIVEN** `find_episodes_by_topic(db, show_id, ["高雄美食"])` invoked against descriptions whose tsvectors store `高雄` and `美食` as separate jieba tokens
- **WHEN** the finder constructs the tsquery
- **THEN** the `:tsquery_text` parameter SHALL be `"高雄 | 美食"` (jieba split + OR-joined), NOT `"高雄美食"` (the raw phrase)
- **AND** rows whose `text_tsvector` matches either token SHALL be returned

#### Scenario: All-stopword topic term falls back to raw term

- **GIVEN** `find_episodes_by_topic(db, show_id, ["節目"])` where `節目` is in `TOPIC_STOPWORDS`
- **WHEN** the finder constructs the tsquery
- **THEN** the per-term jieba pass produces zero kept tokens (the single token `節目` is stopword-filtered)
- **AND** the finder SHALL retain the raw term `"節目"` so the tsquery is `"節目"` rather than empty (the corpus may still match the lexeme even though it's a generic word — the LLM chose to surface it for a reason)
- **AND** the call SHALL NOT short-circuit to an empty result

#### Scenario: Cross-term deduplication preserves first occurrence

- **GIVEN** `find_episodes_by_topic(db, show_id, ["高雄美食", "美食地圖"])` where jieba splits to `[高雄, 美食]` and `[美食, 地圖]` respectively
- **WHEN** the finder constructs the tsquery
- **THEN** `美食` SHALL appear exactly once in the final OR list (first occurrence kept)
- **AND** the `:tsquery_text` parameter SHALL be `"高雄 | 美食 | 地圖"`

#### Scenario: Title-only match surfaces episode missing from description corpus

- **GIVEN** an episode whose `title` contains `歌單` (its `title_tsvector` includes the `歌單` lexeme) AND whose `episode_description_chunks.text_tsvector` rows do NOT contain the `歌單` lexeme
- **WHEN** `find_episodes_by_topic(db, show_id, ["歌單"])` is invoked
- **THEN** the returned list SHALL include that episode
- **AND** the episode SHALL appear exactly once (not duplicated)

##### Example: q25 audit recovery

- **GIVEN** the 6 episodes EP19 / EP84 / EP87 / EP89 / EP96 / EP108 whose titles contain `歌單` but whose descriptions do not
- **WHEN** `find_episodes_by_topic(db, show_id, ["歌單"])` is invoked against the prod corpus
- **THEN** all 6 episodes SHALL be present in the returned list (alongside the previously-matched description-only and title-and-description episodes)

#### Scenario: Description-only match still returned (regression guard)

- **GIVEN** an episode whose `title` does NOT contain the topic term AND at least one of its `episode_description_chunks.text_tsvector` rows DOES contain the term
- **WHEN** `find_episodes_by_topic(db, show_id, [term])` is invoked
- **THEN** the returned list SHALL include that episode (existing behavior preserved after the SQL rewrite)

#### Scenario: Episode matching both pools appears exactly once

- **GIVEN** an episode whose `title_tsvector` matches the tsquery AND whose `episode_description_chunks.text_tsvector` also matches the same tsquery
- **WHEN** `find_episodes_by_topic(db, show_id, [term])` is invoked
- **THEN** the returned list SHALL contain that episode exactly once (distinct by `episodes.id`)
