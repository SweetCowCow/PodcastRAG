# tokenizer-dictionary Specification

## Purpose

TBD - created by archiving change 'r3-1-hybrid-retrieval'. Update Purpose after archive.

## Requirements

### Requirement: Tokeniser service exposes tokenize() backed by jieba + custom dictionary

The backend SHALL expose a `tokenize(text: str) -> list[str]` function in `backend/app/services/tokenizer.py` that returns jieba-segmented tokens of the input string. At process startup, the service SHALL query all rows of `tokenizer_custom_terms` and SHALL register each term with `jieba.add_word(term, weight)` so that custom terms are not split into single characters. The service SHALL be safe for re-initialisation: a `reload_dictionary()` function SHALL clear jieba's user-added words for the current process and re-register from the current DB state.

#### Scenario: Process startup loads dictionary

- **WHEN** a backend / worker / dispatcher / beat process starts
- **THEN** the tokenizer module SHALL run a one-time initialisation that loads all rows from `tokenizer_custom_terms` and calls `jieba.add_word(term, weight)` for each

#### Scenario: Custom term not split into chars

- **GIVEN** the row `term='迪拉胖', weight=100` exists in `tokenizer_custom_terms`
- **WHEN** `tokenize("迪拉胖很煩")` is called after startup loaded the dictionary
- **THEN** the output SHALL contain `"迪拉胖"` as a single token (and SHALL NOT contain `"迪"`, `"拉"`, `"胖"` separately)

#### Scenario: Tokenize ignores leading/trailing whitespace

- **WHEN** `tokenize("   迪拉胖很煩  ")` is called
- **THEN** the result SHALL be the same as `tokenize("迪拉胖很煩")` (the wrapper SHALL strip whitespace before invoking jieba)


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
### Requirement: Admin CRUD endpoints for tokenizer_custom_terms

The backend SHALL expose admin-gated REST endpoints (`require_admin`):

- `GET /admin/tokenizer/terms` — list all rows ordered by `created_at` DESC, **including the `is_show_name` boolean per row**
- `POST /admin/tokenizer/terms` — body `{term: str, weight: int = 100, is_show_name: bool = false}`; insert one row, `created_by_user_id` set to caller
- `PATCH /admin/tokenizer/terms/{id}` — body `{is_show_name: bool}`; update the show-name flag without touching other fields
- `DELETE /admin/tokenizer/terms/{id}` — delete one row by UUID
- `POST /admin/tokenizer/reload` — trigger `reload_dictionary()` in the local process and dispatch a Celery broadcast task to do the same on workers / beat / dispatcher

These endpoints SHALL require an authenticated admin (existing `require_admin` dependency). Anonymous and non-admin authenticated callers SHALL be rejected with HTTP 401 / 403 respectively.

#### Scenario: List includes is_show_name

- **GIVEN** 3 rows exist where one has `is_show_name=true`
- **WHEN** an admin calls `GET /admin/tokenizer/terms`
- **THEN** each item SHALL include `is_show_name` (boolean)
- **AND** the row with `is_show_name=true` SHALL reflect that

#### Scenario: PATCH toggles flag

- **GIVEN** a row currently has `is_show_name=false`
- **WHEN** an admin calls `PATCH /admin/tokenizer/terms/{id}` with body `{"is_show_name": true}`
- **THEN** the response SHALL be HTTP 200 with the updated row
- **AND** subsequent `GET` SHALL show `is_show_name=true`

#### Scenario: Create with is_show_name

- **WHEN** an admin posts `{"term": "大嘻哈時代", "is_show_name": true}`
- **THEN** the inserted row SHALL have `is_show_name=true`

#### Scenario: Adding a duplicate term returns 409

- **GIVEN** `"台通"` already exists
- **WHEN** an admin calls `POST` with the same `term`
- **THEN** the response SHALL be HTTP 409 with `error_code='duplicate_term'`

#### Scenario: Admin reloads dictionary across all processes

- **WHEN** an admin calls `POST /admin/tokenizer/reload`
- **THEN** the local backend process SHALL re-query the table and re-register jieba terms within 5 seconds
- **AND** the response SHALL be HTTP 202

#### Scenario: Non-admin denied

- **WHEN** an authenticated non-admin user calls any `/admin/tokenizer/*` endpoint
- **THEN** the response SHALL be HTTP 403


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
### Requirement: Seed dictionary builder script

The repository SHALL contain `backend/scripts/build_jieba_seed_dict.py`, a CLI tool that scans transcripts for high-frequency multi-character entity candidates that jieba's default tokeniser splits into single characters. It SHALL output a CSV (`docs/jieba_seed_candidates.csv`) with columns `[term, occurrences, sample_episode_titles]` for human review. The CSV is then manually curated, and the curated subset is loaded into `tokenizer_custom_terms` via a separate import command (`python -m backend.scripts.import_jieba_seed --csv <path>`).

#### Scenario: Script outputs CSV ordered by frequency

- **WHEN** the build script runs against a corpus of 354 transcripts
- **THEN** it SHALL produce a CSV containing candidate terms ordered by descending occurrence count
- **AND** each row SHALL include the term, its total occurrence count, and up to 3 sample episode titles where it appears

#### Scenario: Import command persists curated terms with seed_script source

- **WHEN** the import command runs against a curated CSV with 70 rows
- **THEN** 70 rows SHALL be inserted into `tokenizer_custom_terms` with `source='seed_script'`
- **AND** any row whose term already exists SHALL be skipped (logged at INFO level), not failing the whole import

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
### Requirement: Show-name tokens excluded from lexical query

`_build_ts_query(question)` in `backend/app/services/rag.py` SHALL load the set of `term` values from `tokenizer_custom_terms` where `is_show_name = true` and SHALL drop those tokens from the OR-joined `to_tsquery` string after jieba tokenisation. The exclusion SHALL apply only to the lexical (tsvector) side of hybrid retrieval; semantic embedding SHALL be computed against the original full question text unchanged.

The set of show-name tokens SHALL be cached in process memory and refreshed when `reload_dictionary()` is invoked (so admins can toggle the flag and reload to take effect across services).

#### Scenario: Show-name token dropped from ts_query

- **GIVEN** `tokenizer_custom_terms` contains `('這又沒有很屌', is_show_name=true)`
- **WHEN** `_build_ts_query("這又沒有很屌的節目名怎麼來的")` is called after dict load
- **THEN** the returned tsquery string SHALL NOT contain `這又沒有很屌`
- **AND** SHALL still contain `節目名` and `怎麼` (other multi-char tokens)

#### Scenario: Reload picks up flag changes

- **GIVEN** a row with `is_show_name=false` was loaded at startup
- **WHEN** an admin calls `POST /admin/tokenizer/terms/{id}` (or equivalent UPDATE) to set it to `true`
- **AND** then calls `POST /admin/tokenizer/reload`
- **THEN** subsequent `_build_ts_query` calls SHALL drop that token

#### Scenario: Embedding side unaffected

- **WHEN** a query containing a show-name token is embedded
- **THEN** the full question text (including the show-name token) SHALL be passed to the embedding model


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
### Requirement: Single-character token filter removed

The `_build_ts_query` function SHALL accept jieba tokens of any length ≥ 1 (no length-2 minimum). Token filtering SHALL be limited to: (a) whitespace-only tokens, (b) pure-punctuation tokens, (c) tokens dropped per the show-name exclusion above.

#### Scenario: Length-1 tokens accepted

- **GIVEN** a query that yields jieba tokens including single-character entries
- **WHEN** `_build_ts_query` runs
- **THEN** the returned tsquery string SHALL include those length-1 tokens (e.g. `是`, `了`)

(Rationale: R3.1 v3/v4 eval bake-off proved length-1 filtering had zero impact on episode-level recall (v1=v3, v2=v4 across 48 items). Removing it simplifies the code path. The OR-join with `ts_rank` weighting already suppresses common-particle noise.)

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