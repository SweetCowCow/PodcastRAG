# rag-query Specification

## Purpose

TBD - created by archiving change 'rag-query'. Update Purpose after archive.

## Requirements

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


<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->

---
### Requirement: Chunk embeddings generated after successful transcription

The backend SHALL call OpenAI `text-embedding-3-small` to produce a 1536-dimensional vector for each chunk, and SHALL persist chunks with their embeddings into `transcript_chunks` within the same worker task that completed transcription. Chunks SHALL be embedded in batches of at most 64 texts per API call.

#### Scenario: Embeddings persisted on successful transcription

- **WHEN** a `transcribe_episode` worker task successfully persists all transcript segments for an episode
- **THEN** the task SHALL build chunks from those segments, request embeddings via OpenAI, and insert one row per chunk into `transcript_chunks` with the returned 1536-dim vector before setting the transcript status to `completed`

#### Scenario: Embedding failure fails the transcript

- **WHEN** the OpenAI embeddings API raises an exception during chunk embedding
- **THEN** the worker task SHALL set the transcript status to `failed`, SHALL set `error_message` to the exception message (truncated to 2000 characters), and SHALL NOT leave any partial `transcript_chunks` rows for that transcript

#### Scenario: Batching respects size limit

- **WHEN** a transcript produces more than 64 chunks
- **THEN** the worker SHALL split the chunk list into consecutive batches of at most 64 texts and SHALL issue one embeddings request per batch, preserving chunk order


<!-- @trace
source: rag-query
updated: 2026-04-23
code:
  - backend/alembic/versions/c1f2d3e4a5b6_add_rag_tables.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/transcripts.py
  - backend/app/services/__init__.py
  - backend/app/api/query.py
  - backend/alembic/env.py
  - backend/app/core/__init__.py
  - backend/app/models/llm_config.py
  - backend/app/services/chunking.py
  - backend/app/workers/dispatch.py
  - backend/requirements.txt
  - src/AdminPage.jsx
  - backend/app/workers/celery_app.py
  - backend/app/workers/__init__.py
  - backend/.env.example
  - backend/app/services/embedding.py
  - backend/app/services/llm_config.py
  - backend/.dockerignore
  - backend/app/api/admin.py
  - backend/app/core/database.py
  - backend/app/main.py
  - backend/app/services/rag.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/schemas/transcript.py
  - backend/app/services/transcription/base.py
  - backend/app/api/health.py
  - src/Shared.jsx
  - backend/app/schemas/admin.py
  - backend/app/core/bootstrap.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic.ini
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/app/core/config.py
  - backend/app/schemas/episode.py
  - backend/app/services/transcription/factory.py
  - backend/app/services/transcription/openai_provider.py
  - .spectra/spectra.db
  - backend/app/models/transcript.py
  - backend/app/schemas/query.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/alembic/script.py.mako
  - backend/app/models/transcript_segment.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/api/episodes.py
  - backend/Dockerfile
  - src/QueryPage.jsx
  - backend/app/api/shows.py
  - backend/app/models/transcript_chunk.py
  - backend/app/api/__init__.py
  - backend/app/models/episode.py
  - backend/app/models/show.py
  - backend/app/services/transcription/__init__.py
  - backend/docker-compose.yml
  - backend/app/services/rss_parser.py
  - backend/app/workers/tasks.py
  - backend/app/schemas/sync.py
-->

---
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


<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->

---
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


<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->

---
### Requirement: Citation click navigates to transcript with highlight

The frontend ChatBubble citation badge SHALL be interactive. When a user clicks a citation badge, the application SHALL navigate to TranscriptPage for the cited episode using a URL containing the query parameter `?t=<seconds>` where `<seconds>` is the citation's `start_time` formatted with up to one decimal place. TranscriptPage SHALL parse `?t` from `window.location.search` on mount, scroll to the first segment whose `start_time` is closest to the parsed value within a ±5 second window, and apply a 3-second highlighted background that fades out. When no segment falls within the window, TranscriptPage SHALL scroll to the top of the transcript without highlighting any segment. The button label SHALL read `跳到這段內容` when `lang=zh` and `Jump to transcript` when `lang=en`.

#### Scenario: Citation badge click navigates with t URL param

- **WHEN** a user clicks a citation badge in a ChatBubble where the source's `start_time` is `252.6`
- **THEN** the application SHALL navigate to a URL whose path resolves to TranscriptPage for the cited `episode_id` and whose search string contains `t=252.6`

#### Scenario: TranscriptPage highlights segment matched within window

- **GIVEN** TranscriptPage mounts with `window.location.search` containing `t=252.6`
- **AND** the transcript contains a segment with `start_time=251.8`
- **WHEN** the page renders
- **THEN** the page SHALL scroll to the segment whose `start_time=251.8` (the closest within ±5 seconds)
- **AND** the page SHALL apply a 3-second highlighted background to that segment

#### Scenario: TranscriptPage falls back to top when no segment within window

- **GIVEN** TranscriptPage mounts with `t=900.0` but no segment has `start_time` within `[895.0, 905.0]`
- **WHEN** the page renders
- **THEN** the page SHALL scroll to the top of the transcript
- **AND** no segment SHALL be highlighted

#### Scenario: Button label respects language

- **WHEN** the language is `zh` and a citation is rendered
- **THEN** the jump button SHALL display `跳到這段內容`

- **WHEN** the language is `en` and a citation is rendered
- **THEN** the jump button SHALL display `Jump to transcript`


<!-- @trace
source: r2-1-citation-infra
updated: 2026-05-10
code:
  - backend/app/services/rag.py
  - backend/eval/runners/run.py
  - src/App.jsx
  - src/TranscriptPage.jsx
  - CLAUDE.md
  - backend/app/services/citation_parser.py
  - backend/app/services/llm_prompts.py
  - backend/app/schemas/query.py
  - src/QueryPage.jsx
  - src/releaseLog.jsx
  - backend/app/api/query.py
  - src/Shared.jsx
tests:
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_citation_parser.py
-->

---
### Requirement: LLM configuration is a singleton DB row

The backend SHALL store LLM gateway configuration in a `llm_config` table constrained to exactly one row (`id=1`). The row SHALL contain separate `base_url`, `api_key`, and `model` fields for the **answer** model and the **rewrite** model. Each `POST /shows/{show_id}/query` in chat mode SHALL read the current row once per request to construct its clients.

#### Scenario: Config updated via admin endpoint

- **WHEN** an authorized client calls `PUT /admin/llm-config` with new values for any subset of the 6 fields
- **THEN** the backend SHALL update only the provided fields on row `id=1`, SHALL set `updated_at` to the current UTC time, and SHALL return the updated row (with `api_key` fields masked)

#### Scenario: Config read via admin endpoint

- **WHEN** an authorized client calls `GET /admin/llm-config`
- **THEN** the backend SHALL return the current row, with both `answer_api_key` and `rewrite_api_key` replaced by the constant string `"***"` in the response body

#### Scenario: Missing API key rejects chat

- **WHEN** a chat-mode query is issued and either `answer_api_key` or `rewrite_api_key` is empty in the `llm_config` row
- **THEN** the endpoint SHALL return HTTP 400 with an error message indicating the LLM is not configured, and SHALL NOT call any upstream LLM

#### Scenario: Updated config takes effect on next request

- **WHEN** a client updates `llm_config` via `PUT /admin/llm-config` while no query is in flight
- **THEN** the next `POST /shows/{show_id}/query` (chat mode) SHALL use the new `base_url`, `api_key`, and `model` values without requiring a backend restart

<!-- @trace
source: rag-query
updated: 2026-04-23
code:
  - backend/alembic/versions/c1f2d3e4a5b6_add_rag_tables.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/transcripts.py
  - backend/app/services/__init__.py
  - backend/app/api/query.py
  - backend/alembic/env.py
  - backend/app/core/__init__.py
  - backend/app/models/llm_config.py
  - backend/app/services/chunking.py
  - backend/app/workers/dispatch.py
  - backend/requirements.txt
  - src/AdminPage.jsx
  - backend/app/workers/celery_app.py
  - backend/app/workers/__init__.py
  - backend/.env.example
  - backend/app/services/embedding.py
  - backend/app/services/llm_config.py
  - backend/.dockerignore
  - backend/app/api/admin.py
  - backend/app/core/database.py
  - backend/app/main.py
  - backend/app/services/rag.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/schemas/transcript.py
  - backend/app/services/transcription/base.py
  - backend/app/api/health.py
  - src/Shared.jsx
  - backend/app/schemas/admin.py
  - backend/app/core/bootstrap.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic.ini
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/app/core/config.py
  - backend/app/schemas/episode.py
  - backend/app/services/transcription/factory.py
  - backend/app/services/transcription/openai_provider.py
  - .spectra/spectra.db
  - backend/app/models/transcript.py
  - backend/app/schemas/query.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/alembic/script.py.mako
  - backend/app/models/transcript_segment.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/api/episodes.py
  - backend/Dockerfile
  - src/QueryPage.jsx
  - backend/app/api/shows.py
  - backend/app/models/transcript_chunk.py
  - backend/app/api/__init__.py
  - backend/app/models/episode.py
  - backend/app/models/show.py
  - backend/app/services/transcription/__init__.py
  - backend/docker-compose.yml
  - backend/app/services/rss_parser.py
  - backend/app/workers/tasks.py
  - backend/app/schemas/sync.py
-->

---
### Requirement: Query endpoint maps OpenAI exceptions to friendly error responses

The backend SHALL catch OpenAI client exceptions raised during embedding, rewrite, or answer calls within `POST /shows/{show_id}/query` and convert each to an `HTTPException` whose body matches the unified error response schema. The mapping SHALL be:

- `openai.RateLimitError` whose error body code equals `"insufficient_quota"` SHALL produce HTTP 429 with `error_code = "llm_quota_exceeded"`.
- `openai.RateLimitError` for any other reason SHALL produce HTTP 429 with `error_code = "llm_rate_limited"`.
- `openai.AuthenticationError` SHALL produce HTTP 502 with `error_code = "llm_auth_failed"`.
- `openai.APIConnectionError` and `openai.APITimeoutError` SHALL produce HTTP 503 with `error_code = "llm_unavailable"`.

The `provider` field of the error response SHALL be derived from the call site: requests that go through the embeddings service SHALL set `provider = "OpenAI"` (since embeddings always target the official OpenAI endpoint); chat and rewrite requests SHALL set `provider` to the value returned by `infer_provider_label` applied to the configured `answer_base_url` or `rewrite_base_url`.

#### Scenario: Embeddings rate limit returns 429 with quota_exceeded

- **WHEN** the embeddings service raises `openai.RateLimitError` with body `{"error": {"code": "insufficient_quota"}}` during a query request
- **THEN** the endpoint SHALL respond HTTP 429 with body `{"detail": {"error_code": "llm_quota_exceeded", "provider": "OpenAI", "detail": <message>}}`

#### Scenario: Chat rate limit identifies Zeabur AI Hub provider

- **WHEN** the answer model is configured with `answer_base_url` containing `"zeabur"` and the chat call raises `openai.RateLimitError` not matching `insufficient_quota`
- **THEN** the endpoint SHALL respond HTTP 429 with `provider = "Zeabur AI Hub"` and `error_code = "llm_rate_limited"`

#### Scenario: Authentication error returns 502

- **WHEN** any OpenAI client call within the query endpoint raises `openai.AuthenticationError`
- **THEN** the endpoint SHALL respond HTTP 502 with `error_code = "llm_auth_failed"` and the appropriate `provider` label

#### Scenario: Connection error returns 503

- **WHEN** any OpenAI client call within the query endpoint raises `openai.APIConnectionError` or `openai.APITimeoutError`
- **THEN** the endpoint SHALL respond HTTP 503 with `error_code = "llm_unavailable"` and the appropriate `provider` label

#### Scenario: api_health record is preserved across the conversion

- **WHEN** the embeddings or chat service raises an OpenAI exception that the endpoint converts to an `HTTPException`
- **THEN** the underlying service SHALL still record one event via `api_health.record` for the failed call, and the endpoint SHALL NOT emit a duplicate record


<!-- @trace
source: friendly-external-api-errors
updated: 2026-05-01
code:
  - backend/app/main.py
  - backend/app/api/shows.py
  - src/i18n.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/errors.py
  - src/QueryPage.jsx
  - backend/app/services/llm_config.py
  - backend/app/api/query.py
  - index.html
tests:
  - backend/tests/test_provider_label.py
  - backend/tests/conftest.py
  - backend/tests/test_error_responses.py
-->

---
### Requirement: Provider label is inferred from base URL

The backend SHALL provide a function `infer_provider_label(base_url: str | None) -> str` in the LLM configuration module that returns a human-readable label identifying the provider. The function SHALL return `"OpenAI"` when `base_url` is `None` or its hostname ends with `openai.com`, `"Zeabur AI Hub"` when the hostname contains `zeabur`, and the URL hostname (or `"External API"` when the hostname cannot be parsed) otherwise.

#### Scenario: None base_url returns OpenAI

- **WHEN** `infer_provider_label(None)` is called
- **THEN** the function SHALL return `"OpenAI"`

#### Scenario: Official OpenAI base URL returns OpenAI

- **WHEN** `infer_provider_label("https://api.openai.com/v1")` is called
- **THEN** the function SHALL return `"OpenAI"`

#### Scenario: Zeabur AI Hub base URL returns Zeabur AI Hub

- **WHEN** `infer_provider_label("https://aihub-xyz.zeabur.app/v1")` is called
- **THEN** the function SHALL return `"Zeabur AI Hub"`

#### Scenario: Unknown provider falls back to hostname

- **WHEN** `infer_provider_label("https://api.together.xyz/v1")` is called
- **THEN** the function SHALL return `"api.together.xyz"`

<!-- @trace
source: friendly-external-api-errors
updated: 2026-05-01
code:
  - backend/app/main.py
  - backend/app/api/shows.py
  - src/i18n.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/errors.py
  - src/QueryPage.jsx
  - backend/app/services/llm_config.py
  - backend/app/api/query.py
  - index.html
tests:
  - backend/tests/test_provider_label.py
  - backend/tests/conftest.py
  - backend/tests/test_error_responses.py
-->

---
### Requirement: RAG query response includes stable query_id

The `POST /query` endpoint SHALL include a `query_id` field (opaque string, max 64 chars, unique per response) in its JSON response. The frontend SHALL use this `query_id` when posting to `/qa-feedback` and `/events` so server-side rows can be correlated with the originating answer. The `query_id` SHALL be generated server-side (not by the client) and SHALL be present on all successful query responses regardless of whether RAG returned answers.

#### Scenario: Successful query response includes query_id

- **WHEN** a logged-in user calls `POST /query` with a valid question
- **THEN** the JSON response SHALL contain a non-empty `query_id` string

#### Scenario: query_id values are unique across responses

- **GIVEN** the same user issues two consecutive `POST /query` requests with the same body
- **THEN** the two responses SHALL contain different `query_id` values

<!-- @trace
source: r1-ui-feedback-infra
updated: 2026-05-05
code:
  - src/LandingPage.jsx
  - backend/alembic/versions/q5f6a7b8c9d0_add_qa_feedback_and_events.py
  - src/QueryPage.jsx
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/case-studies/zeabur-platform-case-study.md
  - docs/research/competitive-analysis.md
  - docs/case-studies/transcription-queue-discussion.md
  - aisteps-tab.png
  - backend/app/schemas/event.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/api/events.py
  - backend/app/api/qa_feedback.py
  - backend/app/main.py
  - backend/app/models/qa_feedback.py
  - backend/app/core/csrf.py
  - backend/app/schemas/query.py
  - backend/app/schemas/qa_feedback.py
  - docs/case-studies/build-zeabur-pptx.js
  - backend/app/api/query.py
  - src/PodcastSelect.jsx
  - docs/research/competitive-feature-plan.md
  - docs/research/r1-rag-eval-brief.md
  - backend/app/models/event.py
  - backend/app/core/rate_limit.py
  - index.html
  - backend/app/models/__init__.py
tests:
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_qa_feedback_stats.py
  - backend/tests/test_events_api.py
-->

---
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

<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->

---
### Requirement: Search and query responses include context, highlights, and AI summary excerpt

The backend `POST /shows/{show_id}/search` and `POST /shows/{show_id}/query` endpoints SHALL include four additional fields on every result/citation entry: `before_text` (string, the concatenated text of the up to two preceding `transcript_segments` rows joined by single spaces, or empty string when no preceding segments exist), `after_text` (same shape for the up to two following segments), `highlights` (string containing PostgreSQL `ts_headline()` output that wraps query-token matches in `<mark>...</mark>` tags using the same jieba-backed tsvector configuration that retrieval uses, with no other HTML allowed), and `ai_summary_excerpt` (string, the first 60 characters of the episode's `ai_summary` column followed by `…` if truncation occurred, or empty string when no summary exists). For description-source entries (`source="description"`), `before_text` and `after_text` SHALL be empty strings (descriptions have no segment-level neighbours). The response SHALL include a top-level `sources_schema_version` integer set to `1` to support future cache invalidation.

#### Scenario: Transcript source includes two-segment context

- **GIVEN** a transcript chunk whose middle region starts at segment `s5` and ends at segment `s7`, and segments `s3`, `s4` precede `s5` and `s8`, `s9` follow `s7` within the same transcript
- **WHEN** the search endpoint returns this chunk in the response
- **THEN** the entry's `before_text` SHALL equal `"<text of s3> <text of s4>"`
- **AND** the entry's `after_text` SHALL equal `"<text of s8> <text of s9>"`

#### Scenario: First chunk has empty before_text

- **GIVEN** a transcript chunk whose middle region begins at segment `s1` (the first segment of the transcript)
- **WHEN** the chunk is returned in a response
- **THEN** the entry's `before_text` SHALL equal `""`
- **AND** the entry's `after_text` SHALL contain up to two following segments concatenated

#### Scenario: Description source has empty context fields

- **WHEN** a description chunk (`source="description"`) is returned
- **THEN** the entry's `before_text` SHALL equal `""`
- **AND** the entry's `after_text` SHALL equal `""`
- **AND** the entry's `highlights` SHALL still contain `ts_headline()` output computed against the description text

#### Scenario: Highlights wrap matched tokens

- **GIVEN** a chunk whose stored text contains the substring `歌單環節` and the user's query is `這集有歌單嗎`
- **WHEN** the response is constructed
- **THEN** the entry's `highlights` SHALL contain the substring `<mark>歌單</mark>` (or a longer matched span depending on jieba tokenisation) inside a fragment of surrounding context
- **AND** the entry's `highlights` SHALL NOT contain any HTML tag other than `<mark>`

#### Scenario: AI summary excerpt truncates with ellipsis

- **GIVEN** an episode whose `ai_summary` column starts with the 80-character string `迪拉胖在這集邀請了顏色一起聊...（共 80 字）`
- **WHEN** a chunk from this episode is returned
- **THEN** the entry's `ai_summary_excerpt` SHALL contain the first 60 characters of `ai_summary` followed by exactly one `…` character

#### Scenario: Episode without AI summary returns empty excerpt

- **WHEN** a chunk from an episode whose `ai_summary` is NULL or empty is returned
- **THEN** the entry's `ai_summary_excerpt` SHALL equal `""`

#### Scenario: Response carries sources schema version

- **WHEN** any successful response is returned from `/shows/{show_id}/search` or `/shows/{show_id}/query`
- **THEN** the response body SHALL include a top-level integer field `sources_schema_version` equal to `1`


<!-- @trace
source: r2-1-citation-infra
updated: 2026-05-10
code:
  - backend/app/services/rag.py
  - backend/eval/runners/run.py
  - src/App.jsx
  - src/TranscriptPage.jsx
  - CLAUDE.md
  - backend/app/services/citation_parser.py
  - backend/app/services/llm_prompts.py
  - backend/app/schemas/query.py
  - src/QueryPage.jsx
  - src/releaseLog.jsx
  - backend/app/api/query.py
  - src/Shared.jsx
tests:
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_citation_parser.py
-->

---
### Requirement: LLM answer prompt enforces citation, faithfulness, and refusal

The backend `POST /shows/{show_id}/query` answer prompt SHALL be reconstructed so that the configured answer model receives: (a) a system instruction enumerating retrieved sources as a numbered list `[1] [2] [3] …` matching the order returned by hybrid retrieval; (b) a directive that every factual claim in the answer SHALL end with a bracketed reference of the form `[N]` for a single source or `[N,M,...]` for multi-source synthesis; (c) a directive that the model SHALL NOT introduce facts absent from the supplied sources, and SHALL answer 「找不到相關內容，請改用其他關鍵字」 (if `lang=zh`) or `"No relevant content was found. Please try different keywords."` (if `lang=en`) when retrieval returns no results or when no source supports the question. The prompt SHALL preserve the existing requirement to emit JSON containing `answer` and `used_chunk_ids` (see existing requirement "Chat endpoint answers with citations using Tier 2 RAG").

#### Scenario: Answer cites single source

- **GIVEN** retrieval returns three sources numbered `[1] [2] [3]`
- **AND** the answer model produces the sentence `迪拉胖第一次來上節目是 EP1[1]`
- **WHEN** the endpoint serialises the response
- **THEN** the `answer` field SHALL contain the substring `[1]` immediately after the relevant claim

#### Scenario: Answer cites multiple sources

- **GIVEN** retrieval returns four sources `[1] [2] [3] [4]`
- **AND** the answer model produces the sentence `他在 EP1 與 EP134 都聊過這個話題[1,3]`
- **WHEN** the endpoint serialises the response
- **THEN** the `answer` field SHALL contain the substring `[1,3]` immediately after the relevant claim

#### Scenario: Empty retrieval triggers explicit refusal in zh

- **GIVEN** the user's `lang` cookie is `zh` and hybrid retrieval returns zero chunks
- **WHEN** the answer model is invoked with the empty sources list
- **THEN** the `answer` field SHALL contain the substring `找不到相關內容`
- **AND** `citations` SHALL be an empty array

#### Scenario: Empty retrieval triggers explicit refusal in en

- **GIVEN** the user's `lang` cookie is `en` and hybrid retrieval returns zero chunks
- **WHEN** the answer model is invoked with the empty sources list
- **THEN** the `answer` field SHALL contain the substring `No relevant content was found`

#### Scenario: Soft Faithfulness gate (revised 2026-05-10 per RCA evidence)

- **GIVEN** the R1.2 mini-set (`backend/eval/datasets/this-not-that-cool.json`) Faithfulness median was `F_pre` before the prompt change
- **AND** the post-change Faithfulness median is `F_post`
- **WHEN** archive readiness is evaluated
- **THEN** archive SHALL be blocked when `F_post < 0.50` (absolute floor — answers below are catastrophic)
- **AND** archive SHALL proceed with a deferred-fix annotation when `0.50 ≤ F_post < F_pre`
- **AND** the deferred-fix annotation SHALL link to `docs/case-studies/r21-rca-deep-2026-05-10.md` which documents:
  - Judge variance SD = 0.0139 (3 runs, gap is real signal)
  - Root cause is **retrieval recall = 15% drives 58% refusal rate, AND judge gpt-5-nano under-scores correctly-phrased Mandarin refusals (0.51 vs rubric 1.0)**
  - Prompt change is only the trigger, not the root cause (explains 83% of the 0.21 drop)
  - Real fix path: R3.x retrieval + R1.3 judge re-bake-off, not further prompt micro-tuning
- **AND** revisiting Faithfulness with a re-baked judge SHALL be tracked as R2.2 (deferred)


<!-- @trace
source: r2-1-citation-infra
updated: 2026-05-10
code:
  - backend/app/services/rag.py
  - backend/eval/runners/run.py
  - src/App.jsx
  - src/TranscriptPage.jsx
  - CLAUDE.md
  - backend/app/services/citation_parser.py
  - backend/app/services/llm_prompts.py
  - backend/app/schemas/query.py
  - src/QueryPage.jsx
  - src/releaseLog.jsx
  - backend/app/api/query.py
  - src/Shared.jsx
tests:
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_citation_parser.py
-->

---
### Requirement: Citation parser strips invalid refs and degrades gracefully

The backend SHALL implement a citation parser invoked after the answer model returns. Given the raw answer string and the list of source numbers `1..N`, the parser SHALL extract every bracketed reference token of the form `[K]` or `[K,M,...]`. Tokens whose every numeric component lies in `1..N` SHALL be retained verbatim in the answer. Tokens with at least one component outside `1..N` SHALL be removed entirely (including the surrounding brackets). The parser SHALL produce a structured representation `citations_meta: [{sentence_index, ref_ids: [...]}, ...]` mapped per sentence (sentences split on `。`, `！`, `？`, `.`, `!`, `?`) and SHALL include `citations_meta` in the response body for future R2.2 inline rendering. The original `citations` array (chunks referenced via `used_chunk_ids`) SHALL still be returned so that the frontend can render source cards even when the inline reference parsing yields nothing.

#### Scenario: Valid single ref retained

- **GIVEN** the answer text is `這集播了三首[1]`
- **AND** retrieval returned three sources
- **WHEN** the parser runs
- **THEN** the answer string SHALL remain `這集播了三首[1]`
- **AND** `citations_meta` SHALL contain one entry whose `ref_ids` equals `[1]`

#### Scenario: Out-of-range ref stripped

- **GIVEN** the answer text is `這集很精彩[5]`
- **AND** retrieval returned three sources
- **WHEN** the parser runs
- **THEN** the answer string SHALL equal `這集很精彩`
- **AND** `citations_meta` SHALL contain one entry whose `ref_ids` is an empty array

#### Scenario: Multi-ref with one invalid component drops the whole token

- **GIVEN** the answer text is `他在兩集講過[1,9]`
- **AND** retrieval returned three sources
- **WHEN** the parser runs
- **THEN** the answer string SHALL equal `他在兩集講過`
- **AND** `citations_meta` SHALL contain one entry whose `ref_ids` is an empty array

#### Scenario: No bracketed refs at all yields empty meta

- **GIVEN** the answer model returned plain prose with no `[N]` tokens
- **WHEN** the parser runs
- **THEN** the answer string SHALL be unchanged
- **AND** `citations_meta` SHALL be a list of entries each with empty `ref_ids`
- **AND** the response body SHALL still include the full `citations` array

<!-- @trace
source: r2-1-citation-infra
updated: 2026-05-10
code:
  - backend/app/services/rag.py
  - backend/eval/runners/run.py
  - src/App.jsx
  - src/TranscriptPage.jsx
  - CLAUDE.md
  - backend/app/services/citation_parser.py
  - backend/app/services/llm_prompts.py
  - backend/app/schemas/query.py
  - src/QueryPage.jsx
  - src/releaseLog.jsx
  - backend/app/api/query.py
  - src/Shared.jsx
tests:
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_citation_parser.py
-->