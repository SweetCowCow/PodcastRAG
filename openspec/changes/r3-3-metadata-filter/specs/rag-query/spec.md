## MODIFIED Requirements

### Requirement: Semantic search endpoint returns ranked chunks

The backend SHALL expose `POST /shows/{show_id}/search` which SHALL be guarded by the `optional_auth_with_ip_limit` dependency (see auth-system + ip-rate-limit capabilities). The endpoint accepts body `{"question": "<non-empty string>", "k": <optional int 1-50, default 8>}`. The endpoint SHALL embed the question using the configured embedding step, jieba-tokenise the question for lexical matching using the current custom dictionary (see tokenizer-dictionary capability), and perform hybrid retrieval combining semantic (pgvector cosine distance) and lexical (PostgreSQL tsvector ts_rank) signals via Reciprocal Rank Fusion. Retrieval SHALL be performed against three lexical pools — `transcript_chunks.text_tsvector`, `episode_description_chunks.text_tsvector`, AND `episodes.title_tsvector` — combined with the semantic pool over `transcript_chunks` AND `episode_description_chunks`, with each pool weighted by a configurable Python-side constant (default: chunk × 1.0, description × 0.7, title × 0.5). All pools SHALL be filtered to the specified `show_id`, ranked individually, then unioned by RRF score. Each result SHALL carry a `source` discriminator equal to `"transcript"`, `"description"`, or `"title"`. The endpoint SHALL NOT include any LLM-generated answer. The endpoint SHALL NOT decrement `quota_remaining` even for authenticated callers.

#### Scenario: RRF combines semantic and lexical ranks across three pools

- **GIVEN** chunk `A` ranks 3 in semantic, 25 in chunk-lexical, absent from description-lexical, absent from title-lexical
- **AND** the configured RRF weights are chunk=1.0, description=0.7, title=0.5
- **WHEN** the endpoint computes RRF scores with constant `k=60`
- **THEN** chunk `A`'s RRF score SHALL be `1/(60+3) + 1.0 × 1/(60+25) + 0.7 × 1/(60+999) + 0.5 × 1/(60+999)` (absent-side ranks are sentinel 999)

#### Scenario: Title-pool match contributes lexical signal

- **GIVEN** episode `E1` has title `"Ft. 馬世芳"` and the user query is `"馬世芳"`
- **WHEN** the title lexical pool is queried via jieba tokeniser
- **THEN** `E1`'s title SHALL match the tsquery and the corresponding result SHALL appear in the union with `source = "title"`
- **AND** all transcript chunks belonging to `E1` SHALL retain their original `source` discriminator

#### Scenario: Description and transcript results unified by RRF score

- **GIVEN** a transcript chunk with RRF score 0.020 and a description chunk with RRF score 0.025
- **WHEN** the endpoint constructs the final ranked list
- **THEN** the description chunk SHALL appear before the transcript chunk in the response
- **AND** each result SHALL include `source: "transcript"`, `"description"`, or `"title"` matching its origin

#### Scenario: Anonymous request under rate limit returns top-K hybrid results

- **GIVEN** an unauthenticated visitor whose IP counter is 5 and `ip_search_rate_limit_per_day=20`
- **WHEN** the visitor calls `POST /shows/{show_id}/search` with body `{"question": "歌單"}`
- **THEN** the response SHALL be 200 with up to 8 ranked results

### Requirement: Chat endpoint answers with citations using Tier 2 RAG

The backend SHALL expose `POST /shows/{show_id}/query` guarded by `require_authenticated_user` and atomic quota decrement (see user-quota). The endpoint SHALL execute the Tier 2 RAG pipeline: (1) if the request includes a non-empty `messages` history, rewrite the question to a standalone form using the configured rewrite model; (2) call the `entity_extraction` AI step (see query-entity-extraction capability) to extract `{date_range, guests, topics}` from the rewritten question — failure to extract SHALL fail-open with empty entities, NOT raise 5xx; (3) embed the rewritten question AND jieba-tokenise it; (4) perform retrieval combining semantic + three-pool lexical RRF across `transcript_chunks`, `episode_description_chunks`, AND `episodes.title_tsvector`, applying any extracted entity hard filters (`episodes.guests @> :guest_list` and/or `episodes.published_at BETWEEN :start AND :end`); (5) if the extracted entities indicate an enumeration query (non-empty guests OR non-empty date_range OR question matches enumeration rule pattern), populate `enumeration_episodes` field listing all matched episodes (not limited to top-K chunks); (6) generate an answer using the configured answer model with the retrieved chunks as grounding, requesting structured JSON output containing `answer` and `used_chunk_ids`; (7) return the answer together with only the citation chunks referenced in `used_chunk_ids`, plus `enumeration_episodes` when applicable. Description-source citations SHALL be presented to the answer model with a clear marker (e.g. `desc:<episode_id>`) distinguishing them from transcript citations (`ep:<episode_id>@<start_time>`). If JSON parsing of the model output fails, the endpoint SHALL fall back to returning the raw text as `answer` with all retrieved chunks as `citations`. This endpoint SHALL NOT accept anonymous callers and SHALL NOT consult the IP rate limit.

#### Scenario: Hybrid retrieval result feeds answer prompt

- **WHEN** a chat-mode query is issued and hybrid retrieval returns 5 transcript chunks and 3 description chunks
- **THEN** the answer prompt SHALL list all 8 results, each prefixed with `ep:<episode_id>@<start_time>` for transcripts or `desc:<episode_id>` for descriptions
- **AND** the model is permitted to cite either form in `used_chunk_ids`

#### Scenario: Entity extraction fails-open without breaking retrieval

- **WHEN** chat query is processed and the `entity_extraction` step raises an exception or returns invalid JSON
- **THEN** the endpoint SHALL log a warning, treat extracted entities as empty, and continue retrieval without metadata filter
- **AND** the response SHALL be HTTP 200 (not 5xx) with normal `answer` + `citations`

#### Scenario: Guest filter narrows retrieval

- **WHEN** chat query `"馬世芳上過哪幾集"` extracts `guests = ["馬世芳"]`
- **THEN** retrieval SQL SHALL include `episodes.guests @> '["馬世芳"]'::jsonb` filter clause
- **AND** the response SHALL include `enumeration_episodes` listing all episodes where guests contains `"馬世芳"`

#### Scenario: Date filter narrows retrieval

- **WHEN** chat query `"2024 那集講過什麼"` extracts `date_range = (2024-01-01T00:00:00Z, 2024-12-31T23:59:59Z)`
- **THEN** retrieval SQL SHALL include `episodes.published_at BETWEEN :start AND :end` filter clause
- **AND** the response SHALL include `enumeration_episodes` listing all episodes published within the range

#### Scenario: Empty entity result triggers no enumeration

- **WHEN** chat query `"主持人有什麼興趣"` extracts empty entities and does NOT match enumeration rule pattern
- **THEN** `enumeration_episodes` SHALL be `null` in the response
- **AND** retrieval SHALL run with no metadata filter (R3.2 two-layer routing path)

#### Scenario: First turn skips rewrite

- **WHEN** a client calls `POST /shows/{show_id}/query` with an empty or missing `messages` array
- **THEN** the endpoint SHALL NOT call the rewrite model, SHALL embed the original `question` directly, SHALL retrieve via RRF, and SHALL return an answer

#### Scenario: Follow-up turn uses rewritten question for retrieval

- **WHEN** a client calls with a non-empty `messages` history and a new `question` containing a pronoun
- **THEN** the endpoint SHALL call the rewrite model, SHALL use the rewrite output as the retrieval query, and the answer model SHALL receive the original messages plus the new question (not the rewritten form) as conversation input

#### Scenario: Response includes only used citations

- **WHEN** chat mode completes successfully and the model returns valid JSON with `used_chunk_ids`
- **THEN** the response body SHALL contain `answer` (string) and `citations` (array containing only the chunks whose key appears in `used_chunk_ids`)

#### Scenario: Structured output parse failure falls back to full citations

- **WHEN** the answer model returns output that cannot be parsed as JSON or lacks the `answer` key
- **THEN** the endpoint SHALL treat the entire model output as the `answer` string and SHALL return all retrieved chunks as `citations`

#### Scenario: Sliding window limit enforced

- **WHEN** a client sends a `messages` array longer than 10 entries
- **THEN** the endpoint SHALL use only the most recent 10 entries when building prompts

#### Scenario: Anonymous request rejected with 401

- **WHEN** an unauthenticated request reaches `POST /shows/{show_id}/query`
- **THEN** the response SHALL be HTTP 401 with `error_code='not_authenticated'`
- **AND** no embedding or LLM API SHALL be called

## ADDED Requirements

### Requirement: RRF pool weights configurable in Python

The backend SHALL define RRF pool weights as a Python module-level constant `RRF_WEIGHTS` in `app/services/rag.py`, mapping pool name to weight float. The constant SHALL be passed into RRF SQL as a parameter so weights can be tuned without rebuilding any tsvector or DB index.

#### Scenario: Default weights documented

- **WHEN** the system starts with default configuration
- **THEN** `RRF_WEIGHTS` MUST equal `{"chunk": 1.0, "description": 0.7, "title": 0.5}` (semantic pool always 1.0, no override)

#### Scenario: Weight change does not require schema migration

- **WHEN** an operator edits `RRF_WEIGHTS` in source code from 0.5 to 0.3 for the title pool and redeploys
- **THEN** the next chat / search query MUST use the new weight without any alembic migration or tsvector rebuild

### Requirement: Cross-episode enumeration response shape

The chat endpoint response SHALL include an optional `enumeration_episodes` field containing a list of episode references when the query is an enumeration-type question.

#### Scenario: Enumeration episodes returned alongside chunk citations

- **WHEN** chat query extracts non-empty guests entity AND the show has 4 episodes matching `guests @> :guest_list`
- **THEN** the response body SHALL contain `enumeration_episodes` with all 4 entries, each `{episode_id, title, published_at, guests, ai_summary}`
- **AND** `citations` SHALL still contain the answer-model-cited chunks (separate field)

#### Scenario: Non-enumeration query has null enumeration field

- **WHEN** chat query produces empty entities and no enumeration rule pattern match
- **THEN** the response body SHALL set `enumeration_episodes = null`

#### Scenario: Enumeration rule pattern triggers enumeration response

- **WHEN** chat query contains the substring `"哪幾集"` or `"哪集"` or `"哪些集"` even when entity extractor returns empty
- **THEN** the endpoint SHALL run a topic-keyword based filter against `episode_description_chunks` and populate `enumeration_episodes` with matched episodes
