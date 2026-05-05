# rag-query Specification

## Purpose

TBD - created by archiving change 'rag-query'. Update Purpose after archive.

## Requirements

### Requirement: Chunk builder aggregates Whisper segments

The backend SHALL provide a chunk-builder service that groups consecutive `transcript_segments` into `transcript_chunks`. Each chunk SHALL end when either (a) it contains at least 5 segments, or (b) its accumulated duration (`last.end_time - first.start_time`) reaches 60 seconds, whichever comes first. A final partial chunk SHALL be emitted for any remaining segments.

#### Scenario: Segments aggregated by segment-count bound

- **WHEN** the builder consumes an ordered list of segments where 5 consecutive segments span less than 60 seconds
- **THEN** the builder SHALL emit a chunk containing exactly those 5 segments, with `start_time` equal to the first segment's `start_time`, `end_time` equal to the fifth segment's `end_time`, `text` equal to the concatenation of the 5 segment texts joined by single spaces, and `segment_ids` equal to the 5 segment UUIDs in order

#### Scenario: Segments aggregated by duration bound

- **WHEN** the builder consumes segments where the cumulative duration reaches or exceeds 60 seconds before 5 segments are accumulated
- **THEN** the builder SHALL close the current chunk at the segment that caused the duration threshold to be met, and SHALL start a new chunk from the next segment

#### Scenario: Trailing segments flushed

- **WHEN** the builder reaches end-of-input with fewer than 5 accumulated segments and less than 60 seconds accumulated duration
- **THEN** the builder SHALL emit one final chunk containing the remaining segments, provided at least one segment remains


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

The backend SHALL expose `POST /shows/{show_id}/search` which SHALL be guarded by the `optional_auth_with_ip_limit` dependency (see auth-system + ip-rate-limit capabilities). The endpoint accepts body `{"question": "<non-empty string>", "k": <optional int 1-50, default 8>}`. The endpoint SHALL embed the question using the configured embedding step, run pgvector cosine similarity search against `transcript_chunks` filtered to `completed` transcripts belonging to the specified show, and return the top-K chunks ordered by ascending cosine distance. The response SHALL NOT include any LLM-generated answer. The endpoint SHALL NOT decrement `quota_remaining` even for authenticated callers — the cost being controlled is the embedding API call only, and the IP rate limit (for anonymous) plus quota gating on the chat endpoint (for authenticated) are sufficient.

#### Scenario: Anonymous request under rate limit returns top-K chunks

- **GIVEN** an unauthenticated visitor whose IP counter is 5 and `ip_search_rate_limit_per_day=20`
- **WHEN** the visitor calls `POST /shows/{show_id}/search` with body `{"question": "歌單"}`
- **THEN** the IP counter SHALL become 6
- **AND** the embedding API SHALL be called once
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
- **AND** the response SHALL be HTTP 200 with ranked chunks
- **AND** the user's `quota_remaining` SHALL NOT be decremented

#### Scenario: Search excludes other shows

- **WHEN** a search query is issued for `show_id=A` and a semantically closer chunk exists for `show_id=B`
- **THEN** the response SHALL NOT include any chunk whose owning episode belongs to `show_id=B`

#### Scenario: Search excludes incomplete transcripts

- **WHEN** a search query is issued and one episode in the show has a transcript whose `status` is not `completed`
- **THEN** the response SHALL NOT include any chunk from that incomplete transcript

#### Scenario: k parameter is clamped

- **WHEN** the body has `{"k": 100}`
- **THEN** the response SHALL contain at most 50 chunks (the documented upper bound)


<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->

---
### Requirement: Chat endpoint answers with citations using Tier 2 RAG

The backend SHALL expose `POST /shows/{show_id}/query` guarded by `require_authenticated_user` and atomic quota decrement (see user-quota). The endpoint SHALL execute the Tier 2 RAG pipeline: (1) if the request includes a non-empty `messages` history, rewrite the question to a standalone form using the configured rewrite model; (2) embed the (rewritten) question; (3) retrieve top 8 chunks via pgvector; (4) generate an answer using the configured answer model with the retrieved chunks as grounding, requesting structured JSON output containing `answer` and `used_chunk_ids`; (5) return the answer together with only the citation chunks referenced in `used_chunk_ids`. If JSON parsing of the model output fails, the endpoint SHALL fall back to returning the raw text as `answer` with all retrieved chunks as `citations`. This endpoint SHALL NOT accept anonymous callers and SHALL NOT consult the IP rate limit (the auth + quota gates are the cost control).

#### Scenario: First turn skips rewrite

- **WHEN** a client calls `POST /shows/{show_id}/query` with an empty or missing `messages` array
- **THEN** the endpoint SHALL NOT call the rewrite model, SHALL embed the original `question` directly, SHALL retrieve chunks, and SHALL return an answer from the answer model

#### Scenario: Follow-up turn uses rewritten question for retrieval

- **WHEN** a client calls with a non-empty `messages` history and a new `question` that contains a pronoun or implicit reference
- **THEN** the endpoint SHALL call the rewrite model with the history and the new question, SHALL use the rewrite model's output as the retrieval query, and the answer model SHALL receive the original user messages plus the new question (not the rewritten form) as its conversation input

#### Scenario: Response includes only used citations

- **WHEN** chat mode completes successfully and the model returns valid JSON with `used_chunk_ids`
- **THEN** the response body SHALL contain `answer` (string) and `citations` (array containing only the chunks whose `ep:<episode_id>@<start_time>` key appears in `used_chunk_ids`), where `citations` length SHALL be less than or equal to the number of retrieved chunks

#### Scenario: Structured output parse failure falls back to full citations

- **WHEN** the answer model returns output that cannot be parsed as JSON or lacks the `answer` key
- **THEN** the endpoint SHALL treat the entire model output as the `answer` string and SHALL return all retrieved chunks as `citations`

#### Scenario: Sliding window limit enforced

- **WHEN** a client sends a `messages` array longer than 10 entries (5 user + 5 assistant)
- **THEN** the endpoint SHALL use only the most recent 10 entries when building prompts for both rewrite and answer models

#### Scenario: Anonymous request rejected with 401

- **WHEN** an unauthenticated request reaches `POST /shows/{show_id}/query`
- **THEN** the response SHALL be HTTP 401 with `error_code='not_authenticated'`
- **AND** no embedding or LLM API SHALL be called


<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->

---
### Requirement: Citation click navigates to transcript with highlight

The frontend ChatBubble citation badge SHALL be interactive. When a user clicks a citation badge, the application SHALL navigate to TranscriptPage for the cited episode and SHALL scroll to and visually highlight the transcript segment at the cited `start_time`. The highlight SHALL be applied as a background color accent for 3 seconds then fade out.

#### Scenario: Citation badge click navigates to transcript

- **WHEN** a user clicks a citation badge in a ChatBubble
- **THEN** the application SHALL navigate to TranscriptPage with `selectedEpisode.id` equal to the citation's `episode_id` and `highlightTime` equal to the citation's `start_time`

#### Scenario: Transcript highlights cited segment on load

- **WHEN** TranscriptPage mounts with a non-null `highlightTime`
- **THEN** the page SHALL scroll to the first segment whose `start_time` is closest to `highlightTime` and SHALL apply a 3-second highlighted background to that segment


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


<!-- @trace
source: query-ux-improvements
updated: 2026-04-24
code:
  - src/App.jsx
  - src/TranscriptPage.jsx
  - src/QueryPage.jsx
  - src/PodcastSelect.jsx
  - backend/app/schemas/episode.py
  - backend/app/api/shows.py
  - backend/app/api/episodes.py
  - backend/app/schemas/show.py
  - backend/app/services/rag.py
  - backend/app/api/query.py
  - .mcp.json
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