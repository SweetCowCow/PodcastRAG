## MODIFIED Requirements

### Requirement: Chunk builder aggregates Whisper segments

The backend SHALL provide a chunk-builder service that groups consecutive `transcript_segments` into `transcript_chunks` with overlap context. Each chunk's MIDDLE region (the segments that "belong" to the chunk) SHALL contain between 5 and 10 segments and SHALL span between 30 and 60 seconds, whichever bound is reached first. The builder SHALL prefer to close a chunk at a segment-gap exceeding 1.5 seconds when the current middle region has at least 5 segments and at least 30 seconds. Each chunk's `text` field SHALL contain the concatenation of one preceding overlap segment + the middle segments + one following overlap segment, joined by single spaces; `segment_ids` SHALL contain ONLY the middle-region segment UUIDs (not the overlap segments); `start_time` SHALL equal the first middle segment's `start_time`; `end_time` SHALL equal the last middle segment's `end_time`. A final partial chunk SHALL be emitted for any remaining middle segments at end-of-input.

#### Scenario: Middle region closed at 60s upper bound

- **WHEN** the builder consumes segments where the cumulative duration of the middle region reaches or exceeds 60 seconds before 10 segments are accumulated and no segment-gap > 1.5s has been observed
- **THEN** the builder SHALL close the chunk at the segment that crossed the 60s threshold

#### Scenario: Middle region closed at 10-segment upper bound

- **WHEN** 10 consecutive segments span less than 60 seconds with no segment-gap > 1.5s
- **THEN** the builder SHALL close the chunk after exactly 10 middle segments

#### Scenario: Middle region closed early at natural gap

- **WHEN** the middle region has accumulated at least 5 segments AND at least 30 seconds AND the next segment begins more than 1.5 seconds after the previous segment ends
- **THEN** the builder SHALL close the current chunk before the gap and start a new chunk after the gap

#### Scenario: Overlap context appended to chunk text

- **GIVEN** a chunk whose middle region is segments `[s2, s3, s4, s5, s6]`
- **WHEN** the builder serialises the chunk
- **THEN** the chunk's `text` SHALL equal `"<text of s1> <text of s2> <text of s3> <text of s4> <text of s5> <text of s6> <text of s7>"` (one segment of overlap on each side)
- **AND** `segment_ids` SHALL equal `[s2.id, s3.id, s4.id, s5.id, s6.id]` (no overlap)
- **AND** `start_time` SHALL equal `s2.start_time`
- **AND** `end_time` SHALL equal `s6.end_time`

#### Scenario: First chunk has no preceding overlap

- **WHEN** the builder closes the first chunk of a transcript whose middle starts at segment `s1`
- **THEN** the chunk's `text` SHALL begin at the middle's first segment (no preceding overlap exists) and SHALL include one trailing overlap segment if available

#### Scenario: Last chunk has no trailing overlap

- **WHEN** the builder closes the final chunk and no further segments remain after the middle region
- **THEN** the chunk's `text` SHALL include one preceding overlap segment if available and SHALL end at the middle's last segment

#### Scenario: Trailing partial middle flushed

- **WHEN** the builder reaches end-of-input with fewer than 5 accumulated middle segments and less than 30 seconds accumulated middle duration
- **THEN** the builder SHALL emit one final chunk containing the remaining segments as the middle region (with overlap as available), provided at least one middle segment remains

### Requirement: Semantic search endpoint returns ranked chunks

The backend SHALL expose `POST /shows/{show_id}/search` which SHALL be guarded by the `optional_auth_with_ip_limit` dependency (see auth-system + ip-rate-limit capabilities). The endpoint accepts body `{"question": "<non-empty string>", "k": <optional int 1-50, default 8>}`. The endpoint SHALL embed the question using the configured embedding step, jieba-tokenise the question for lexical matching using the current custom dictionary (see tokenizer-dictionary capability), and perform hybrid retrieval combining semantic (pgvector cosine distance) and lexical (PostgreSQL tsvector ts_rank) signals via Reciprocal Rank Fusion. Retrieval SHALL be performed against `transcript_chunks` AND `episode_description_chunks` (see episode-description-index capability) filtered to the specified `show_id`, both ranked by RRF and then unioned, with the final top-K returned by descending RRF score. Each result SHALL carry a `source` discriminator equal to `"transcript"` or `"description"`. The endpoint SHALL NOT include any LLM-generated answer. The endpoint SHALL NOT decrement `quota_remaining` even for authenticated callers.

#### Scenario: RRF combines semantic and lexical ranks

- **GIVEN** `transcript_chunks` semantic top-50 returns chunk `A` at rank 3 and chunk `B` at rank 50
- **AND** `transcript_chunks` lexical top-50 returns chunk `A` at rank 25 and chunk `B` at rank 1
- **WHEN** the endpoint computes RRF scores with constant `k=60`
- **THEN** chunk `A`'s RRF score SHALL equal `1/(60+3) + 1/(60+25)` and chunk `B`'s RRF score SHALL equal `1/(60+50) + 1/(60+1)`
- **AND** chunk `A` SHALL rank higher (~0.0276 vs ~0.0255 — semantic-rank-3 contribution outweighs B's lexical-rank-1 with k=60)

#### Scenario: Chunk hit only on one side scored with placeholder rank

- **WHEN** chunk `C` is in the semantic top-50 at rank 10 but absent from the lexical top-50
- **THEN** chunk `C`'s RRF score SHALL be computed using `1/(60+10) + 1/(60+999)` where the absent-side rank is treated as a sentinel beyond the cutoff

#### Scenario: Description and transcript results unified by RRF score

- **GIVEN** a transcript chunk with RRF score 0.020 and a description chunk with RRF score 0.025
- **WHEN** the endpoint constructs the final ranked list
- **THEN** the description chunk SHALL appear before the transcript chunk in the response
- **AND** each result SHALL include `source: "transcript"` or `source: "description"` matching its origin

#### Scenario: Anonymous request under rate limit returns top-K hybrid results

- **GIVEN** an unauthenticated visitor whose IP counter is 5 and `ip_search_rate_limit_per_day=20`
- **WHEN** the visitor calls `POST /shows/{show_id}/search` with body `{"question": "歌單"}`
- **THEN** the IP counter SHALL become 6
- **AND** the embedding API SHALL be called once
- **AND** jieba tokenisation SHALL run once on the question
- **AND** the response SHALL be HTTP 200 with up to 8 ranked chunks (default k)
- **AND** the response SHALL NOT contain an `answer` field

#### Scenario: Anonymous request over rate limit is rejected without embedding call

- **GIVEN** an unauthenticated visitor whose IP counter is at the limit
- **WHEN** the visitor calls `POST /shows/{show_id}/search`
- **THEN** the response SHALL be HTTP 429 with `error_code='ip_rate_limited'`
- **AND** no embedding API call SHALL be made

#### Scenario: Authenticated request bypasses IP limit

- **GIVEN** an authenticated user from an IP whose counter is at the daily limit
- **WHEN** the user calls `POST /shows/{show_id}/search`
- **THEN** the request SHALL be processed
- **AND** the IP counter SHALL NOT be incremented
- **AND** the response SHALL be HTTP 200 with hybrid ranked results
- **AND** the user's `quota_remaining` SHALL NOT be decremented

#### Scenario: Search excludes other shows

- **WHEN** a search query is issued for `show_id=A` and a higher-scoring chunk exists for `show_id=B`
- **THEN** the response SHALL NOT include any chunk (transcript or description) whose owning episode belongs to `show_id=B`

#### Scenario: Search excludes incomplete transcripts

- **WHEN** a search query is issued and one episode in the show has a transcript whose `status` is not `completed`
- **THEN** the response SHALL NOT include any transcript chunk from that incomplete transcript
- **AND** the response MAY still include the episode's description chunk if its description is non-empty

#### Scenario: k parameter is clamped

- **WHEN** the body has `{"k": 100}`
- **THEN** the response SHALL contain at most 50 chunks (the documented upper bound)

### Requirement: Chat endpoint answers with citations using Tier 2 RAG

The backend SHALL expose `POST /shows/{show_id}/query` guarded by `require_authenticated_user` and atomic quota decrement (see user-quota). The endpoint SHALL execute the Tier 2 RAG pipeline: (1) if the request includes a non-empty `messages` history, rewrite the question to a standalone form using the configured rewrite model; (2) embed the (rewritten) question AND jieba-tokenise it; (3) retrieve top 8 results via the same hybrid (RRF) retrieval as `/search`, against both `transcript_chunks` and `episode_description_chunks`; (4) generate an answer using the configured answer model with the retrieved chunks as grounding, requesting structured JSON output containing `answer` and `used_chunk_ids`; (5) return the answer together with only the citation chunks referenced in `used_chunk_ids`. Description-source citations SHALL be presented to the answer model with a clear marker (e.g. `desc:<episode_id>`) distinguishing them from transcript citations (`ep:<episode_id>@<start_time>`). If JSON parsing of the model output fails, the endpoint SHALL fall back to returning the raw text as `answer` with all retrieved chunks as `citations`. This endpoint SHALL NOT accept anonymous callers and SHALL NOT consult the IP rate limit.

#### Scenario: Hybrid retrieval result feeds answer prompt

- **WHEN** a chat-mode query is issued and hybrid retrieval returns 5 transcript chunks and 3 description chunks
- **THEN** the answer prompt SHALL list all 8 results, each prefixed with `ep:<episode_id>@<start_time>` for transcripts or `desc:<episode_id>` for descriptions
- **AND** the model is permitted to cite either form in `used_chunk_ids`

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

### Requirement: Hybrid retrieval implemented as a single SQL CTE

The hybrid retrieval logic SHALL be expressed as a single SQL statement using common table expressions (CTEs) — one for the semantic ranking, one for the lexical ranking, and one for the RRF score computation — followed by `FULL OUTER JOIN` and `ORDER BY rrf_score DESC LIMIT :k`. The implementation SHALL NOT introduce any third-party retrieval library (e.g., LlamaIndex, LangChain, Haystack). Both the per-side cutoff (top 50 each) and the RRF constant (`k_rrf = 60`) SHALL be defined as named constants in `backend/app/services/rag.py`.

#### Scenario: Single round-trip to Postgres per retrieval

- **WHEN** the retrieval function executes for one query
- **THEN** the application SHALL issue exactly one SQL statement covering both semantic and lexical paths plus the RRF combination

#### Scenario: No external retrieval library imported

- **WHEN** project source code under `backend/` is scanned for imports
- **THEN** no module SHALL import from `llama_index`, `langchain`, `langchain_*`, `haystack`, or any equivalent retrieval framework

##### Example: RRF constant

| Constant       | Value | Defined in                                |
| -------------- | ----- | ----------------------------------------- |
| `RRF_K`        | 60    | `backend/app/services/rag.py`             |
| `RRF_PER_SIDE` | 50    | `backend/app/services/rag.py`             |
| `RETRIEVAL_TOP_K` | 8  | `backend/app/services/rag.py` (existing)  |
