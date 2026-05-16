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


<!-- @trace
source: r3-3-metadata-filter
updated: 2026-05-16
code:
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/eval/datasets/this-not-that-cool.json
  - docs/ai-steps.md
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/embedding.py
  - backend/app/services/rag.py
  - src/AdminTokenizerTab.jsx
  - index.html
  - backend/app/api/admin/__init__.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/tokenizer.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/schemas/query.py
  - backend/app/models/ai_step.py
  - src/AdminPage.jsx
  - backend/app/services/query_entity.py
  - backend/app/services/topic_segmentation.py
  - backend/app/models/episode.py
  - src/TranscriptPage.jsx
  - backend/scripts/backfill_guests.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/eval/datasets/_pending_review.json
  - CLAUDE.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/eval/datasets/_schema.json
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/scripts/backfill_topic_labels.py
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/app/schemas/episode_guests.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/api/shows.py
  - backend/app/api/query.py
  - backend/eval/metrics/recall.py
  - backend/eval/datasets/README.md
  - backend/app/services/rss_parser.py
  - docs/roadmap.md
  - backend/app/services/sync.py
  - backend/eval/scripts/validate_schema.py
  - src/ReleaseLogPage.jsx
  - backend/app/services/description_rechunker.py
  - src/releaseLog.jsx
  - backend/eval/runners/run.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/chunking_status.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/key_resolver.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/Shared.jsx
  - backend/app/workers/celery_app.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/workers/tasks.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/app/schemas/query_entity.py
  - backend/eval/scripts/build_golden_set.py
tests:
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_query_entity.py
-->

---
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


<!-- @trace
source: r3-3-chat-enum-grounding
updated: 2026-05-16
code:
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
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

---
### Requirement: Two-layer episode routing SHALL be disabled by default

The retrieval pipeline (`backend/app/services/rag.py`) SHALL NOT apply two-layer episode routing by default. The `_should_skip_routing()` predicate SHALL return `True` whenever the `ENABLE_TWO_LAYER_ROUTING` environment variable is unset, empty, or equal to any case-insensitive form of `"false"`. The legacy routing pass MAY be re-enabled for diagnostics by setting `ENABLE_TWO_LAYER_ROUTING=true`. The hybrid retrieval (RRF over `transcript_chunks` and `episode_description_chunks` filtered by `show_id`) SHALL operate over the full show without a pre-filter to a routed subset of `episode_id` values.

#### Scenario: No env var set yields full-show retrieval

- **GIVEN** `ENABLE_TWO_LAYER_ROUTING` is not set in the backend process environment
- **WHEN** a caller invokes `POST /shows/{show_id}/search` with any valid `question`
- **THEN** `_should_skip_routing(question)` SHALL return `True`
- **AND** `retrieve_hybrid` SHALL be invoked with `episode_id_filter=None`
- **AND** the returned chunks SHALL be drawn from the full set of `transcript_chunks` and `episode_description_chunks` belonging to the show (subject only to the RRF top-K cutoff)

#### Scenario: Env var set to "true" re-enables routing for diagnostics

- **GIVEN** `ENABLE_TWO_LAYER_ROUTING=true` is set in the backend process environment
- **WHEN** a caller invokes `POST /shows/{show_id}/search` with a question whose jieba tokenisation yields at least 2 multi-character tokens
- **THEN** `_should_skip_routing(question)` SHALL return `False`
- **AND** the retrieval pipeline SHALL invoke `route_episodes` to obtain a top-K episode list
- **AND** `retrieve_hybrid` SHALL be invoked with `episode_id_filter` set to that list

#### Scenario: Env var "false" is functionally equivalent to unset

- **GIVEN** `ENABLE_TWO_LAYER_ROUTING=false` is set in the backend process environment
- **WHEN** a caller invokes `POST /shows/{show_id}/search`
- **THEN** `_should_skip_routing(question)` SHALL return `True`
- **AND** retrieval SHALL behave identically to the unset case

---
### Requirement: `embedding_v2` columns and ivfflat indexes exist on chunk tables

The DB SHALL have nullable `embedding_v2 vector(3072)` columns on both `transcript_chunks` and `episode_description_chunks`. Each column SHALL have an `ivfflat` cosine ANN index with `lists` parameter scaled to row count (transcript: 200, description: 50). Migration SHALL be applied via alembic; downgrade SHALL fully remove columns and indexes.

#### Scenario: post-migration columns exist

- **GIVEN** alembic upgrade head has run successfully
- **WHEN** `\d transcript_chunks` is inspected
- **THEN** `embedding_v2 vector(3072)` SHALL be present
- **AND** `idx_transcript_chunks_emb_v2_cosine` USING ivfflat SHALL be present

#### Scenario: downgrade is clean

- **GIVEN** alembic upgrade head then alembic downgrade -1 have run
- **WHEN** `\d transcript_chunks` is inspected
- **THEN** `embedding_v2` column SHALL NOT exist
- **AND** `idx_transcript_chunks_emb_v2_cosine` SHALL NOT exist

---
### Requirement: `route_episodes` returns distinct episode_ids and prefers v2 ranking

`_ROUTE_EPISODES_SQL` (the first-layer two-layer routing query in `backend/app/services/rag.py`) SHALL return at most `k` **distinct** episode_ids, not `k` chunk-row results. For each candidate episode, its representative cosine distance SHALL be computed from the episode's v2 chunks if it has any, falling back to v1 otherwise (same prefer-v2 policy as retrieval).

The previous SQL `SELECT e.id ... ORDER BY d.embedding <=> :qv LIMIT :k` returned chunk-row level results, which after v1+v2 coexistence (~16× pool growth) caused 4-5 episodes' chunks to consume the top-10 budget, hard-filtering retrieval to the wrong episode set. See case study root cause #3.

#### Scenario: Routing returns k distinct episode_ids

- **GIVEN** a show has 10 v2 chunks for episode E1 and 1 v1 chunk for E2 (only)
- **WHEN** `route_episodes(show_id, query_embedding, k=2)` is called
- **THEN** the result SHALL contain exactly 2 elements: `[E1.id, E2.id]` (in any order)
- **AND** the result SHALL NOT contain duplicate episode_ids

#### Scenario: Routing prefers v2 chunks for ranking when present

- **GIVEN** episode E has both v1 and v2 chunks
- **WHEN** routing computes E's cosine distance for ranking purposes
- **THEN** the distance SHALL be the minimum cosine distance over E's v2 chunks
- **AND** E's v1 chunks SHALL NOT influence the distance value

#### Scenario: Routing falls back to v1 when episode has no v2

- **GIVEN** episode E has only v1 chunks (no v2)
- **AND** another episode in the same show has v2 chunks
- **WHEN** routing computes ranking
- **THEN** E SHALL still be eligible for top-K via its v1 chunk's cosine distance

---
### Requirement: prefer-v2 SQL uses PG-friendly semi-join form

The prefer-v2 WHERE clause in `_DESC_RRF_SQL`, `_DESC_SEMANTIC_ONLY_SQL`, and `_ROUTE_EPISODES_SQL` SHALL be written such that the PostgreSQL planner uses a hash semi-join (not a per-row nested loop subquery) for the "episodes-with-v2" sub-select. The implementation SHALL verify this via `EXPLAIN ANALYZE` against the pilot show before deploying.

#### Scenario: EXPLAIN ANALYZE shows hash semi-join

- **GIVEN** the modified retrieval SQL is run against a show with mixed v1/v2 chunks
- **WHEN** `EXPLAIN ANALYZE SELECT ... FROM ...` is captured locally
- **THEN** the plan SHALL include a `Hash Semi Join` or `Hash Anti Join` node (or equivalent)
- **AND** SHALL NOT include a `SubPlan` that re-executes per outer row

---
### Requirement: Description chunks carry `chunking_version` and `chunk_index`

The `episode_description_chunks` table SHALL include a `chunking_version smallint NOT NULL DEFAULT 1` column and a `chunk_index smallint NOT NULL DEFAULT 0` column. All rows existing before this migration SHALL be backfilled to `(chunking_version=1, chunk_index=0)` by the column DEFAULT. Newer chunking strategies (re-chunked variants) SHALL be written as rows with `chunking_version >= 2`. The chunk model SHALL expose both fields via SQLAlchemy.

#### Scenario: Existing rows backfilled to v1

- **GIVEN** rows existed in `episode_description_chunks` before this change
- **WHEN** the migration `t8_chunking_version_description_chunks` runs `upgrade()`
- **THEN** every existing row SHALL have `chunking_version = 1` and `chunk_index = 0`
- **AND** the columns SHALL be `NOT NULL`

#### Scenario: New rows can be written at v2

- **GIVEN** the migration has been applied
- **WHEN** an indexer writes a row with `chunking_version=2, chunk_index=0`
- **THEN** the row SHALL be persisted without violating any constraint
- **AND** a query for the same `episode_id` SHALL return both the v1 row and the v2 row

---
### Requirement: Composite unique on `(episode_id, chunking_version, chunk_index)` replaces per-episode unique

The `episode_description_chunks` table SHALL NOT have a single-column `UNIQUE(episode_id)` constraint. It SHALL have a `UNIQUE(episode_id, chunking_version, chunk_index)` constraint named `uq_desc_chunk_episode_version_index`. Two rows that share `episode_id` but differ in `chunking_version` or `chunk_index` SHALL be allowed to coexist.

#### Scenario: (episode, v1) and (episode, v2) coexist

- **GIVEN** a row `(episode_id=E, chunking_version=1, chunk_index=0)` already exists
- **WHEN** the indexer attempts to insert `(episode_id=E, chunking_version=2, chunk_index=0)`
- **THEN** the insert SHALL succeed

#### Scenario: Duplicate (episode, version, index) rejected

- **GIVEN** a row `(episode_id=E, chunking_version=2, chunk_index=5)` exists
- **WHEN** another insert with the same `(episode_id, chunking_version, chunk_index)` triplet runs
- **THEN** the database SHALL trigger the UPSERT `on_conflict_do_update` path on the new constraint
- **AND** no duplicate row SHALL be created

---
### Requirement: `retrieve_hybrid` pools v1 and v2 description chunks together

The description-side hybrid retrieval SQL (`_DESC_RRF_SQL` and `_DESC_SEMANTIC_ONLY_SQL` in `backend/app/services/rag.py`) SHALL NOT filter rows by `chunking_version`. The RRF pool SHALL contain all `chunking_version` variants for a given show, and ranking SHALL be decided solely by hybrid score. Callers SHALL NOT need to specify a `chunking_version` to retrieve results.

#### Scenario: Mixed v1+v2 pool ranks by score

- **GIVEN** a show has both v1 and v2 description chunks for some of its episodes
- **WHEN** `retrieve_descriptions()` is called for that show
- **THEN** the result hits MAY include both v1 and v2 chunks
- **AND** the ordering SHALL be by RRF score (or semantic distance when lexical pathway is empty), not by `chunking_version`

---
### Requirement: `ChunkHit` exposes `chunking_version` metadata

The `ChunkHit` dataclass SHALL include a `chunking_version: int` field with default value `1`. For description hits, the value SHALL reflect the row's `chunking_version` column. For transcript hits, the value SHALL remain the default `1` (transcript chunks are not versioned by this change).

#### Scenario: Description hit carries its row's version

- **GIVEN** a v2 description chunk wins RRF and enters top-K
- **WHEN** the API returns the corresponding `ChunkHit`
- **THEN** `chunk_hit.chunking_version` SHALL equal `2`

#### Scenario: Transcript hit defaults to v1

- **GIVEN** a transcript chunk enters top-K
- **WHEN** the API returns the corresponding `ChunkHit`
- **THEN** `chunk_hit.chunking_version` SHALL equal `1`
- **AND** no transcript-side query SHALL reference a `chunking_version` column

---
### Requirement: Dedup collapses same-episode multi-version description hits

When two description hits from the same `episode_id` but different `chunking_version` both enter the candidate pool, the dedup step SHALL retain only the hit with the higher RRF score (or lower semantic distance when in semantic-only fallback). The retained hit's `chunking_version` and `chunk_index` SHALL be preserved as metadata.

#### Scenario: v1 and v2 hits from same episode collapsed

- **GIVEN** a candidate pool contains `(episode=E, source=description, v=1, score=0.4)` and `(episode=E, source=description, v=2, score=0.6)`
- **WHEN** the dedup step runs
- **THEN** the output SHALL contain exactly one hit for episode E
- **AND** that hit SHALL have `chunking_version = 2`

---
### Requirement: Description indexer accepts `chunking_version` and `chunk_index` keyword parameters

`index_episode_description()` in `backend/app/services/description_indexer.py` SHALL accept keyword-only parameters `chunking_version: int = 1` and `chunk_index: int = 0`. The UPSERT SHALL key conflict resolution on the composite `(episode_id, chunking_version, chunk_index)` index. The empty-content delete pathway SHALL scope its `DELETE` to the same `(episode_id, chunking_version)` pair so it does not remove rows of another version.

#### Scenario: Default call writes v1 row

- **GIVEN** an existing caller invokes `index_episode_description(episode_id=E, text="...")` without naming `chunking_version`
- **WHEN** the indexer runs
- **THEN** the row written SHALL have `chunking_version=1, chunk_index=0`
- **AND** behaviour SHALL be identical to pre-change behaviour for v1-only data

#### Scenario: Versioned call writes v2 row without disturbing v1

- **GIVEN** a v1 row for episode E already exists
- **WHEN** `index_episode_description(episode_id=E, chunking_version=2, chunk_index=3, text="...")` is called
- **THEN** a new row `(E, 2, 3)` SHALL be inserted
- **AND** the existing `(E, 1, 0)` row SHALL remain unchanged

#### Scenario: Empty-content delete only scoped to one version

- **GIVEN** episode E has both v1 and v2 description rows
- **WHEN** `index_episode_description(episode_id=E, chunking_version=2, text="")` runs and triggers the delete-existing-empty pathway
- **THEN** only `(E, 2, *)` rows SHALL be deleted
- **AND** `(E, 1, *)` rows SHALL remain in place

---
### Requirement: `cleanup_v1_description_chunks.py` script is idempotent, dry-run-default, and v2-aware

The cleanup script at `backend/scripts/cleanup_v1_description_chunks.py` SHALL require `--show-id`. Without `--execute` it SHALL only print a plan (dry-run). It SHALL refuse to delete v1 rows for any show where at least one episode has no v2 chunk, unless `--force` is supplied. Deletion SHALL be scoped to `WHERE show_id = ? AND chunking_version = 1` and SHALL be per-episode transactional.

#### Scenario: Dry-run prints plan only

- **GIVEN** the script is invoked without `--execute`
- **WHEN** it finishes
- **THEN** no `DELETE` SHALL have been issued
- **AND** the printed plan SHALL include episode counts (`total`, `with_v2`, `missing_v2`)

#### Scenario: Refuses to delete when episodes lack v2 chunks

- **GIVEN** a show has 163 episodes but only 100 have v2 chunks
- **WHEN** the script runs with `--execute` but without `--force`
- **THEN** it SHALL exit with non-zero status
- **AND** no v1 rows SHALL be deleted

#### Scenario: --force overrides safeguard

- **GIVEN** the same condition as above
- **WHEN** the script runs with `--execute --force`
- **THEN** all v1 rows for the given show SHALL be deleted
- **AND** the operator SHALL accept the consequence that 63 episodes will have no description chunk afterwards

---
### Requirement: `chunking-status` admin endpoint reports v1/v2 breakdown

`GET /admin/chunking-status` SHALL be available to admin-authenticated requests and SHALL return, for every show, the episode total, the count of v1 description chunks, and the count of v2 description chunks. Non-admin callers SHALL receive `401` or `403`.

#### Scenario: Admin sees per-show breakdown

- **GIVEN** an admin-authenticated session
- **WHEN** the client requests `GET /admin/chunking-status`
- **THEN** the response SHALL contain one entry per show with `show_id`, `title`, `episode_total`, `v1_chunks`, `v2_chunks`
- **AND** for a show that has not yet been re-chunked, `v2_chunks` SHALL equal `0`

#### Scenario: Non-admin rejected

- **GIVEN** a non-admin or unauthenticated request
- **WHEN** it hits `GET /admin/chunking-status`
- **THEN** the response status SHALL be `401` or `403`

---
### Requirement: Description hit cap is tunable via `RAG_DESCRIPTION_CAP` env

The backend SHALL read `RAG_DESCRIPTION_CAP` at module import time. The value SHALL be an integer >= 0 and SHALL override the in-code `DESCRIPTION_CAP` constant used by `retrieve_hybrid` to bound the number of `source == "description"` hits in the top-K result. When `RAG_DESCRIPTION_CAP` is unset, malformed (non-integer), or negative, the in-code default SHALL be used and a single warning SHALL be logged to stderr describing the fallback. Changing this env variable SHALL require a service restart to take effect.

#### Scenario: env unset uses in-code default

- **GIVEN** `RAG_DESCRIPTION_CAP` is unset
- **WHEN** the backend imports `app.services.rag`
- **THEN** the runtime cap SHALL equal the in-code `DESCRIPTION_CAP` default
- **AND** no warning SHALL be logged

#### Scenario: env value 0 fully excludes description hits

- **GIVEN** `RAG_DESCRIPTION_CAP=0`
- **WHEN** `/shows/{show_id}/search` is invoked with a question that would normally produce description hits
- **THEN** the response top-K SHALL contain zero items with `source == "description"`

#### Scenario: malformed env falls back with warning

- **GIVEN** `RAG_DESCRIPTION_CAP=abc`
- **WHEN** the backend imports `app.services.rag`
- **THEN** the runtime cap SHALL equal the in-code default
- **AND** a single warning line SHALL be emitted on stderr naming both the malformed value and the fallback value


<!-- @trace
source: r3-2-retrieval-fix
updated: 2026-05-13
code:
  - backend/app/services/description_indexer.py
  - backend/eval/scripts/build_golden_set.py
  - backend/app/api/admin/chunking_status.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/workers/tasks.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/services/description_rechunker.py
  - src/releaseLog.jsx
  - backend/app/models/transcript_chunk.py
  - backend/app/services/rag.py
  - backend/app/services/key_resolver.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/models/episode.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/embedding.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/api/admin/__init__.py
  - docs/roadmap.md
tests:
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_rag_embedding_v2_flag.py
-->

---
### Requirement: Show-name term filtering is tunable via `RAG_SHOW_NAME_FILTER` env

The backend SHALL read `RAG_SHOW_NAME_FILTER` at module import time. When the value (case-insensitive) is `"false"`, `"0"`, or `"off"`, the `_build_ts_query` lexical query builder SHALL NOT drop tokens listed in `tokenizer.get_show_name_terms()`. Any other value (or unset) SHALL preserve current strip behaviour. The semantic / embedding path SHALL be unaffected regardless of this flag. Changing this env variable SHALL require a service restart to take effect.

#### Scenario: env unset preserves current strip behaviour

- **GIVEN** `RAG_SHOW_NAME_FILTER` is unset
- **AND** `tokenizer.get_show_name_terms()` contains `"這又沒有很屌"`
- **WHEN** `_build_ts_query("節目名「這又沒有很屌」是怎麼來的？")` is called
- **THEN** the returned tsquery SHALL NOT contain `"這又沒有很屌"` as a term

#### Scenario: env set to false retains show-name tokens

- **GIVEN** `RAG_SHOW_NAME_FILTER=false`
- **AND** `tokenizer.get_show_name_terms()` contains `"這又沒有很屌"`
- **WHEN** `_build_ts_query("節目名「這又沒有很屌」是怎麼來的？")` is called
- **THEN** the returned tsquery SHALL contain `"這又沒有很屌"` as a term

#### Scenario: embedding side never affected

- **GIVEN** any value of `RAG_SHOW_NAME_FILTER`
- **WHEN** `/shows/{show_id}/search` embeds the question
- **THEN** the full question text (including any show-name term) SHALL be embedded; no token SHALL be stripped from the embedding input

<!-- @trace
source: r3-2-retrieval-fix
updated: 2026-05-13
code:
  - backend/app/services/description_indexer.py
  - backend/eval/scripts/build_golden_set.py
  - backend/app/api/admin/chunking_status.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/workers/tasks.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/services/description_rechunker.py
  - src/releaseLog.jsx
  - backend/app/models/transcript_chunk.py
  - backend/app/services/rag.py
  - backend/app/services/key_resolver.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/models/episode.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/embedding.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/api/admin/__init__.py
  - docs/roadmap.md
tests:
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_rag_embedding_v2_flag.py
-->

---
### Requirement: Two-layer retrieval — first-layer episode routing

The retrieval pipeline SHALL contain a first-layer routing step `route_episodes(db, show_id, query_embedding, k=10)` that returns the top-`k` `episode_id` values for the query, ranked solely by cosine similarity between `query_embedding` and `episode_description_chunks.embedding`. The routing SHALL JOIN through `episodes` to enforce the `show_id` filter and SHALL exclude episodes whose description chunk is missing.

The default `k` SHALL be 10. Routing SHALL be skipped when the question text yields fewer than 2 jieba tokens of length ≥ 2 (entity-only or single-word queries) — in that case the second-layer hybrid retrieval SHALL run against the full show without an episode filter.

#### Scenario: Top-10 episodes returned by description cosine

- **GIVEN** a show with 162 episodes each carrying a non-null `episode_description_chunks` row
- **WHEN** `route_episodes(db, show_id, query_embedding, k=10)` is called
- **THEN** exactly 10 `episode_id` values SHALL be returned
- **AND** the values SHALL be ordered by ascending cosine distance to `query_embedding`

#### Scenario: Skip routing for entity-only short query

- **GIVEN** a question containing only one jieba token of length ≥ 2 (e.g. just "迪拉胖")
- **WHEN** the search endpoint runs
- **THEN** routing SHALL NOT be invoked
- **AND** the second-layer hybrid retrieval SHALL run against the entire show

#### Scenario: Routing limited by show

- **WHEN** routing is invoked for `show_id=A` while another show `B` has higher-similarity descriptions
- **THEN** the returned `episode_id` list SHALL contain only episodes whose `episodes.show_id = A`


<!-- @trace
source: r3-2-two-layer-topic-seg
updated: 2026-05-13
code:
  - backend/app/models/episode.py
  - backend/app/models/transcript_segment.py
  - backend/app/api/admin/__init__.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/schemas/tokenizer.py
  - backend/app/services/rag.py
  - src/TranscriptPage.jsx
  - src/ReleaseLogPage.jsx
  - backend/app/services/topic_segmentation.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/services/description_rechunker.py
  - backend/app/models/show.py
  - backend/app/services/description_indexer.py
  - backend/app/workers/tasks.py
  - backend/app/services/embedding.py
  - backend/app/models/tokenizer_term.py
  - backend/app/api/admin/tokenizer.py
  - backend/app/api/admin/topic_seg.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/workers/celery_app.py
  - src/AdminTopicSegAuditTab.jsx
  - backend/scripts/backfill_topic_labels.py
  - CLAUDE.md
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - src/Shared.jsx
  - backend/alembic/versions/s7f8a9b0c1d2_r32_topic_seg.py
  - backend/app/api/admin/chunking_status.py
  - src/releaseLog.jsx
  - backend/app/schemas/query.py
  - backend/app/schemas/topic_seg.py
  - backend/eval/scripts/build_golden_set.py
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/eval/runners/run.py
  - backend/app/models/episode_description_chunk.py
  - backend/scripts/backfill_embedding_v2.py
  - .github/workflows/backend-tests.yml
  - backend/scripts/pilot_reembed_descriptions.py
  - src/AdminTokenizerTab.jsx
  - backend/app/services/key_resolver.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/api/query.py
  - docs/roadmap.md
  - backend/app/services/llm_prompts.py
  - index.html
  - src/AdminPage.jsx
  - backend/app/services/tokenizer.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/core/csrf.py
tests:
  - backend/tests/test_eval_metric_level.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_tokenizer_show_name_filter.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_topic_segmentation.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_route_episodes.py
  - backend/tests/test_admin_topic_seg.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_rag_query_response_shape.py
-->

---
### Requirement: Two-layer retrieval — second-layer episode-filtered hybrid

`retrieve_hybrid(db, show_id, query_embedding, question, k=8, episode_id_filter=None)` SHALL accept an optional `episode_id_filter: list[UUID] | None` parameter. When provided and non-empty, both the transcript-side and description-side CTEs SHALL include `episode_id IN :episode_id_filter` in their `WHERE` clauses (joining through `episodes` for transcript_chunks).

When `episode_id_filter` is `None` or empty, the function SHALL behave identically to its R3.1 form (search across the entire show).

#### Scenario: Filter restricts both sides

- **GIVEN** `episode_id_filter = [E1, E2, E3]`
- **WHEN** `retrieve_hybrid` is called
- **THEN** every result SHALL belong to one of `{E1, E2, E3}`
- **AND** transcript chunks from other episodes SHALL NOT appear even if their semantic distance is lower

#### Scenario: None filter falls back to full show

- **WHEN** `retrieve_hybrid(...)` is called with `episode_id_filter=None`
- **THEN** the SQL SHALL omit the `episode_id IN ...` predicate
- **AND** the result set SHALL be identical to R3.1 behaviour


<!-- @trace
source: r3-2-two-layer-topic-seg
updated: 2026-05-13
code:
  - backend/app/models/episode.py
  - backend/app/models/transcript_segment.py
  - backend/app/api/admin/__init__.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/schemas/tokenizer.py
  - backend/app/services/rag.py
  - src/TranscriptPage.jsx
  - src/ReleaseLogPage.jsx
  - backend/app/services/topic_segmentation.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/services/description_rechunker.py
  - backend/app/models/show.py
  - backend/app/services/description_indexer.py
  - backend/app/workers/tasks.py
  - backend/app/services/embedding.py
  - backend/app/models/tokenizer_term.py
  - backend/app/api/admin/tokenizer.py
  - backend/app/api/admin/topic_seg.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/workers/celery_app.py
  - src/AdminTopicSegAuditTab.jsx
  - backend/scripts/backfill_topic_labels.py
  - CLAUDE.md
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - src/Shared.jsx
  - backend/alembic/versions/s7f8a9b0c1d2_r32_topic_seg.py
  - backend/app/api/admin/chunking_status.py
  - src/releaseLog.jsx
  - backend/app/schemas/query.py
  - backend/app/schemas/topic_seg.py
  - backend/eval/scripts/build_golden_set.py
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/eval/runners/run.py
  - backend/app/models/episode_description_chunk.py
  - backend/scripts/backfill_embedding_v2.py
  - .github/workflows/backend-tests.yml
  - backend/scripts/pilot_reembed_descriptions.py
  - src/AdminTokenizerTab.jsx
  - backend/app/services/key_resolver.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/api/query.py
  - docs/roadmap.md
  - backend/app/services/llm_prompts.py
  - index.html
  - src/AdminPage.jsx
  - backend/app/services/tokenizer.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/core/csrf.py
tests:
  - backend/tests/test_eval_metric_level.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_tokenizer_show_name_filter.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_topic_segmentation.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_route_episodes.py
  - backend/tests/test_admin_topic_seg.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_rag_query_response_shape.py
-->

---
### Requirement: Description hits capped in top-K

The merge step inside `retrieve_hybrid` SHALL cap the number of `source='description'` hits in the returned top-K to at most `DESCRIPTION_CAP` (a named constant in `backend/app/services/rag.py`). The cap SHALL default to 3. Excess description hits SHALL be replaced (in rank order) by the next-best transcript hits if any are available; if no transcript replacements remain, the description hits SHALL be returned to fill the slot.

#### Scenario: Cap of 3 description hits

- **GIVEN** RRF-merged ranking yields 5 description hits before any transcript hit
- **WHEN** the function returns top-K=8
- **THEN** the result SHALL contain at most 3 description hits
- **AND** at least 5 transcript hits if that many exist post-merge

#### Scenario: Cap waived when transcript pool is exhausted

- **GIVEN** RRF-merged ranking yields 4 description hits and 0 transcript hits (e.g. show with empty transcript_chunks)
- **WHEN** the function returns top-K=8
- **THEN** the result MAY contain all 4 description hits even though that exceeds `DESCRIPTION_CAP`

##### Example: Cap behaviour

| RRF order | source | included in top-8? |
| --- | --- | --- |
| 1 | description | yes (1/3) |
| 2 | description | yes (2/3) |
| 3 | description | yes (3/3) |
| 4 | description | no (cap hit) |
| 5 | transcript | yes |
| 6 | description | no |
| 7 | transcript | yes |
| 8 | transcript | yes |

<!-- @trace
source: r3-2-two-layer-topic-seg
updated: 2026-05-13
code:
  - backend/app/models/episode.py
  - backend/app/models/transcript_segment.py
  - backend/app/api/admin/__init__.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/schemas/tokenizer.py
  - backend/app/services/rag.py
  - src/TranscriptPage.jsx
  - src/ReleaseLogPage.jsx
  - backend/app/services/topic_segmentation.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/services/description_rechunker.py
  - backend/app/models/show.py
  - backend/app/services/description_indexer.py
  - backend/app/workers/tasks.py
  - backend/app/services/embedding.py
  - backend/app/models/tokenizer_term.py
  - backend/app/api/admin/tokenizer.py
  - backend/app/api/admin/topic_seg.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/workers/celery_app.py
  - src/AdminTopicSegAuditTab.jsx
  - backend/scripts/backfill_topic_labels.py
  - CLAUDE.md
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - src/Shared.jsx
  - backend/alembic/versions/s7f8a9b0c1d2_r32_topic_seg.py
  - backend/app/api/admin/chunking_status.py
  - src/releaseLog.jsx
  - backend/app/schemas/query.py
  - backend/app/schemas/topic_seg.py
  - backend/eval/scripts/build_golden_set.py
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/eval/runners/run.py
  - backend/app/models/episode_description_chunk.py
  - backend/scripts/backfill_embedding_v2.py
  - .github/workflows/backend-tests.yml
  - backend/scripts/pilot_reembed_descriptions.py
  - src/AdminTokenizerTab.jsx
  - backend/app/services/key_resolver.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/api/query.py
  - docs/roadmap.md
  - backend/app/services/llm_prompts.py
  - index.html
  - src/AdminPage.jsx
  - backend/app/services/tokenizer.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/core/csrf.py
tests:
  - backend/tests/test_eval_metric_level.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_tokenizer_show_name_filter.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_topic_segmentation.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_route_episodes.py
  - backend/tests/test_admin_topic_seg.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_rag_query_response_shape.py
-->

---
### Requirement: RRF pool weights configurable in Python

The backend SHALL define RRF pool weights as a Python module-level constant `RRF_WEIGHTS` in `app/services/rag.py`, mapping pool name to weight float. The constant SHALL be passed into RRF SQL as a parameter so weights can be tuned without rebuilding any tsvector or DB index.

#### Scenario: Default weights documented

- **WHEN** the system starts with default configuration
- **THEN** `RRF_WEIGHTS` MUST equal `{"chunk": 1.0, "description": 0.7, "title": 0.5}` (semantic pool always 1.0, no override)

#### Scenario: Weight change does not require schema migration

- **WHEN** an operator edits `RRF_WEIGHTS` in source code from 0.5 to 0.3 for the title pool and redeploys
- **THEN** the next chat / search query MUST use the new weight without any alembic migration or tsvector rebuild


<!-- @trace
source: r3-3-metadata-filter
updated: 2026-05-16
code:
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/eval/datasets/this-not-that-cool.json
  - docs/ai-steps.md
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/embedding.py
  - backend/app/services/rag.py
  - src/AdminTokenizerTab.jsx
  - index.html
  - backend/app/api/admin/__init__.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/tokenizer.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/schemas/query.py
  - backend/app/models/ai_step.py
  - src/AdminPage.jsx
  - backend/app/services/query_entity.py
  - backend/app/services/topic_segmentation.py
  - backend/app/models/episode.py
  - src/TranscriptPage.jsx
  - backend/scripts/backfill_guests.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/eval/datasets/_pending_review.json
  - CLAUDE.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/eval/datasets/_schema.json
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/scripts/backfill_topic_labels.py
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/app/schemas/episode_guests.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/api/shows.py
  - backend/app/api/query.py
  - backend/eval/metrics/recall.py
  - backend/eval/datasets/README.md
  - backend/app/services/rss_parser.py
  - docs/roadmap.md
  - backend/app/services/sync.py
  - backend/eval/scripts/validate_schema.py
  - src/ReleaseLogPage.jsx
  - backend/app/services/description_rechunker.py
  - src/releaseLog.jsx
  - backend/eval/runners/run.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/chunking_status.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/key_resolver.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/Shared.jsx
  - backend/app/workers/celery_app.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/workers/tasks.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/app/schemas/query_entity.py
  - backend/eval/scripts/build_golden_set.py
tests:
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_query_entity.py
-->

---
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


<!-- @trace
source: r3-3-chat-enum-grounding
updated: 2026-05-16
code:
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
-->

---
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

<!-- @trace
source: r3-3-chat-enum-grounding
updated: 2026-05-16
code:
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
-->