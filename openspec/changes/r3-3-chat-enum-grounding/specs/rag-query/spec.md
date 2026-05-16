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
- **THEN** `enumeration_episodes` SHALL contain all episodes whose `episode_description_chunks.text_tsvector @@ to_tsquery('simple', '歌單')` matches
- **AND** `enumeration_total` SHALL equal the length of that list
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

#### Scenario: Grounding block truncates beyond 30 episodes

- **GIVEN** enumeration_episodes contains 50 entries
- **WHEN** the answer prompt is constructed
- **THEN** the grounding block SHALL list only the first 30 episodes (ordered by published_at DESC)
- **AND** the block header SHALL read `## 相關集數清單（共 50 集，以下列出最新 30 集）`
- **AND** `enumeration_episodes` in the response body SHALL still contain all 50 (frontend handles progressive display separately)

#### Scenario: Date filter narrows retrieval

- **WHEN** chat query `"2024 那集講過什麼"` extracts `date_range = (2024-01-01T00:00:00Z, 2024-12-31T23:59:59Z)`
- **THEN** retrieval SQL SHALL include `episodes.published_at BETWEEN :start AND :end` filter clause
- **AND** the response SHALL include `enumeration_episodes` listing all episodes published within the range

#### Scenario: Guest AND topic both present, intersection has results

- **GIVEN** chat query `"馬世芳那幾集講過家常菜"` extracts `guests = ["馬世芳"]` AND `topics = ["家常菜"]`
- **WHEN** the chat endpoint processes the query AND the AND-intersection yields 1 episode (EP143)
- **THEN** `enumeration_episodes` SHALL contain that 1 episode
- **AND** the grounding block header SHALL read `## 相關集數清單（共 1 集）` (no fallback marker)

#### Scenario: Guest AND topic both present, intersection is empty — fallback to guest-only

- **GIVEN** chat query `"馬世芳那幾集講過烤肉"` extracts `guests = ["馬世芳"]` AND `topics = ["烤肉"]`
- **WHEN** the AND-intersection of guests+topics yields 0 episodes AND guest-only filter yields 1 episode (EP143)
- **THEN** `enumeration_episodes` SHALL contain that 1 episode (the guest-only result)
- **AND** the grounding block header SHALL read `## ⚠ 沒有完全相符的集數，以下是「馬世芳」全部上過的集數（共 1 集）`
- **AND** the answer text SHALL explicitly mention that no episode matched both constraints

#### Scenario: Empty enumeration result keeps the section semantic

- **GIVEN** chat query extracts a guest name that matches zero episodes (e.g. `guests = ["林志炫"]` where no episode has this guest)
- **WHEN** the chat endpoint processes the query
- **THEN** `enumeration_episodes` SHALL be `[]` (empty list, NOT null) AND `enumeration_total` SHALL be 0
- **AND** the grounding block SHALL contain the line `## 沒有找到相符的集數`
- **AND** the answer text SHALL explicitly state that no matching episode was found

#### Scenario: First turn skips rewrite

- **WHEN** a client calls `POST /shows/{show_id}/query` with an empty or missing `messages` array
- **THEN** the endpoint SHALL NOT call the rewrite model, SHALL embed the original `question` directly, SHALL retrieve via RRF, and SHALL return an answer

#### Scenario: Follow-up turn uses rewritten question for retrieval

- **WHEN** a client calls with a non-empty `messages` history and a new `question` containing a pronoun
- **THEN** the endpoint SHALL call the rewrite model, SHALL use the rewrite output as the retrieval query, and the answer model SHALL receive the original messages plus the new question (not the rewritten form) as conversation input

#### Scenario: Response includes only used citations

- **WHEN** chat mode completes successfully and the model returns valid JSON with `used_chunk_ids`
- **THEN** the response body SHALL contain `answer` (string) and `citations` (array containing only the chunks whose key appears in `used_chunk_ids`)

#### Scenario: Structured output parse failure falls back via salvage regex

- **WHEN** the answer model returns output that cannot be parsed as JSON
- **THEN** the endpoint SHALL attempt to salvage the `answer` field via the malformed-JSON regex (R3.3) AND return that as the `answer` string with all retrieved chunks as `citations`
- **AND** if the regex also fails to extract an answer field, the endpoint SHALL return the raw text as `answer` with all retrieved chunks as `citations`

#### Scenario: Sliding window limit enforced

- **WHEN** a client sends a `messages` array longer than 10 entries
- **THEN** the endpoint SHALL use only the most recent 10 entries when building prompts

#### Scenario: Anonymous request rejected with 401

- **WHEN** an unauthenticated request reaches `POST /shows/{show_id}/query`
- **THEN** the response SHALL be HTTP 401 with `error_code='not_authenticated'`
- **AND** no embedding or LLM API SHALL be called

### Requirement: Cross-episode enumeration response shape

The chat endpoint response SHALL include an optional `enumeration_episodes` field containing a list of episode references when the query is an enumeration-type question, AND an optional `enumeration_total: int | None` field carrying the full count (which MAY exceed the number of entries when the grounding block truncates).

#### Scenario: Enumeration episodes returned alongside chunk citations

- **WHEN** chat query extracts non-empty guests entity AND the show has 4 episodes matching `guests @> :guest_list`
- **THEN** the response body SHALL contain `enumeration_episodes` with all 4 entries, each `{episode_id, title, published_at, guests, ai_summary}`
- **AND** `enumeration_total` SHALL equal 4
- **AND** `citations` SHALL still contain the answer-model-cited chunks (separate field)

#### Scenario: Non-enumeration query has null enumeration fields

- **WHEN** chat query produces empty entities AND no enumeration rule pattern match
- **THEN** the response body SHALL set `enumeration_episodes = null` AND `enumeration_total = null`

#### Scenario: Empty filter result keeps fields populated

- **WHEN** chat query triggers enumeration (entity OR rule pattern) but the filter SQL yields 0 episodes
- **THEN** `enumeration_episodes` SHALL be `[]` (empty list) AND `enumeration_total` SHALL be 0
- **AND** the response body SHALL NOT set these fields to `null` (null vs empty list distinguishes "did not trigger" from "triggered but no match")

#### Scenario: Enumeration rule pattern triggers topic-filtered enumeration

- **WHEN** chat query contains substring `[哪那]幾集` / `[哪那]集` / `[哪那]些集` AND entity extractor returns empty entities
- **THEN** the endpoint SHALL jieba-tokenise the question, drop tokens in `TOPIC_STOPWORDS`, AND use the remaining multi-char terms as topic_terms for the topic-filter SQL
- **AND** `enumeration_episodes` SHALL contain only episodes whose `episode_description_chunks.text_tsvector` matches the topic_terms
- **AND** the endpoint SHALL NOT fall back to "list every episode of the show"

## ADDED Requirements

### Requirement: Topic-driven enumeration SQL filter

The backend SHALL expose three async finder functions in `backend/app/services/episode_finders.py` — `find_episodes_by_guest(db, show_id, guests)`, `find_episodes_by_topic(db, show_id, topic_terms)`, `find_episodes_by_date_range(db, show_id, start, end)` — each returning `list[EpisodeRef]` ordered by `published_at DESC NULLS LAST`. The topic finder SHALL join `episode_description_chunks` and filter by `text_tsvector @@ to_tsquery('simple', :topic_terms)` (terms joined by ` | `). The combiner in `_compute_enumeration_episodes` SHALL dispatch to these finders based on the extracted entities AND combine results per the AND-with-fallback semantics defined in the chat endpoint requirement.

#### Scenario: find_episodes_by_topic uses description_chunks tsvector

- **GIVEN** a show with 25 episodes whose description tsvector matches `to_tsquery('simple', '歌單')`
- **WHEN** `find_episodes_by_topic(db, show_id, ["歌單"])` is invoked
- **THEN** the result SHALL contain exactly those 25 episodes (DISTINCT by episode_id) ordered by `published_at DESC`
- **AND** the function SHALL NOT touch `transcript_chunks.text_tsvector`

#### Scenario: find_episodes_by_guest uses jsonb containment

- **GIVEN** an `episodes.guests` JSONB column with row containing `["馬世芳"]`
- **WHEN** `find_episodes_by_guest(db, show_id, ["馬世芳"])` is invoked
- **THEN** the SQL SHALL include `guests @> CAST(:guests AS jsonb)` AND the row SHALL appear in the result
- **AND** rows with empty `guests` SHALL NOT appear

#### Scenario: find_episodes_by_date_range BETWEEN bound

- **WHEN** `find_episodes_by_date_range(db, show_id, 2024-01-01T00:00:00Z, 2024-12-31T23:59:59Z)` is invoked
- **THEN** the SQL SHALL include `published_at BETWEEN :start AND :end` AND episodes outside the range SHALL be excluded

#### Scenario: TOPIC_STOPWORDS strips generic tokens

- **GIVEN** a question `"節目裡的歌單哪幾集講過"` jieba-tokenised to `["節目", "裡", "的", "歌單", "哪幾集", "講", "過"]`
- **WHEN** the topic-term extraction passes through `TOPIC_STOPWORDS` filter
- **THEN** the resulting topic_terms SHALL be `["歌單", "講"]` (note: 1-char tokens dropped by length filter, `節目` / `的` / `哪幾集` dropped by stopword set)
- **AND** `find_episodes_by_topic(db, show_id, ["歌單", "講"])` SHALL be invoked with the cleaned list
