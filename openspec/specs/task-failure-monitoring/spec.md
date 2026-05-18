# task-failure-monitoring Specification

## Purpose

TBD - created by archiving change 'task-failure-monitoring-and-circuit-breaker'. Update Purpose after archive.

## Requirements

### Requirement: Persisted task failure log

The backend SHALL maintain a `task_failure_log` table that records every Celery task failure with the following columns: `id` (UUID PK), `task_name` (string), `task_args_json` (jsonb), `failure_type` (enum: `permanent` | `transient` | `unknown`), `error_class` (string), `error_message` (text, truncated to 4KB), `provider_id` (nullable string: `openai` | `aihub` | `zsend`), `retry_count` (int), `failed_at` (timestamptz), `alerted_at` (nullable timestamptz), `recovered_at` (nullable timestamptz). Each Celery task SHALL register a `Task.on_failure` handler that writes one row to this table on every final failure (after retry exhaustion or for permanent errors immediately).

#### Scenario: Permanent error writes one row immediately

- **GIVEN** a `transcribe_episode` task hits an `InvalidApiKeyError` (HTTP 401) classified as permanent
- **WHEN** the task fails
- **THEN** exactly one row SHALL be inserted into `task_failure_log` with `failure_type='permanent'`, `provider_id='openai'`, `retry_count=0`, `failed_at=NOW()`

#### Scenario: Transient error writes one row after retries exhausted

- **GIVEN** a `classify_episode_topics` task fails 3 times with `httpx.TimeoutException` (transient)
- **WHEN** Celery exhausts `max_retries=3`
- **THEN** exactly one row SHALL be inserted into `task_failure_log` with `failure_type='transient'`, `retry_count=3`

#### Scenario: Failure log table has retention cleanup

- **GIVEN** `task_failure_log` rows older than 30 days exist
- **WHEN** the daily cleanup beat task runs
- **THEN** rows with `failed_at < NOW() - INTERVAL '30 days'` SHALL be deleted


<!-- @trace
source: task-failure-monitoring-and-circuit-breaker
updated: 2026-05-19
code:
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - .tmp/citation-unify-q3.png
  - .tmp/citation-unify-q1.png
  - backend/app/models/__init__.py
  - backend/app/api/query.py
  - src/releaseLog.jsx
  - backend/app/services/exceptions.py
  - backend/app/services/failure_log.py
  - backend/app/schemas/query.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - backend/app/main.py
  - backend/app/api/admin_circuit.py
  - src/QueueTab.jsx
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/workers/failure_hooks.py
  - backend/app/schemas/query_entity.py
  - backend/app/workers/usage_alert.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - docs/roadmap.md
  - backend/app/api/admin/chunking_status.py
  - backend/app/workers/appeal_digest.py
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/schemas/episode_guests.py
  - backend/app/workers/circuit_probe.py
  - backend/app/models/account_appeal.py
  - backend/app/models/episode.py
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - src/Shared.jsx
  - backend/app/models/transcript_chunk.py
  - src/ServiceStatusTab.jsx
  - src/AdminTokenizerTab.jsx
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/eval/runners/run.py
  - backend/app/services/sync.py
  - backend/app/api/appeal.py
  - backend/app/api/shows.py
  - src/CitationEvidenceCollapse.jsx
  - src/ProviderUsageTab.jsx
  - src/App.jsx
  - src/AdminPage.jsx
  - backend/alembic/versions/a5b6c7d8e9f0_add_task_failure_log_and_circuit_state.py
  - backend/app/workers/eval_reminder.py
  - backend/app/models/task_failure_log.py
  - src/AppealModal.jsx
  - backend/scripts/pilot_reembed_descriptions.py
  - docs/ai-steps.md
  - backend/app/services/zsend.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/errors.py
  - backend/app/services/citation_parser.py
  - src/QueryPage.jsx
  - backend/app/services/episode_finders.py
  - backend/app/services/circuit_breaker.py
  - backend/app/workers/tasks.py
  - backend/app/models/transcription_queue.py
  - .tmp/citation-unify-q2.png
  - .tmp/citation-unify-zh-all.png
  - CLAUDE.md
  - backend/eval/scripts/validate_schema.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/workers/dispatcher.py
  - backend/app/models/service_circuit_state.py
  - backend/app/services/provider_usage/__init__.py
  - backend/app/services/embedding.py
  - src/TranscriptPage.jsx
  - backend/app/services/transcription/openai_provider.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - backend/app/workers/failure_alert.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/summary_ops.py
  - backend/eval/datasets/README.md
  - backend/app/workers/lifecycle.py
  - backend/app/workers/quota_digest.py
  - backend/app/workers/topic_task.py
  - entrypoint.sh
  - backend/scripts/backfill_guests.py
  - backend/app/services/tokenizer.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/description_rechunker.py
  - backend/app/api/auth.py
  - backend/eval/metrics/recall.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - backend/app/workers/celery_app.py
  - backend/app/services/key_resolver.py
  - backend/app/api/admin/__init__.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/schemas/appeal.py
  - backend/app/services/rag.py
  - backend/app/services/rss_parser.py
  - backend/eval/datasets/_pending_review.json
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/core/csrf.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/services/error_classifier.py
  - backend/.env.example
  - backend/app/models/episode_description_chunk.py
  - backend/app/core/config.py
  - docs/celery-queues.md
  - backend/app/workers/summary_task.py
  - backend/app/models/ai_step.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/api/admin_provider_usage.py
  - backend/scripts/backfill_title_tsv.py
  - index.html
  - backend/app/api/admin_processing_stats.py
  - backend/app/workers/usage_collector.py
  - backend/app/services/description_indexer.py
tests:
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_error_classifier.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_failure_alert.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_admin_summary_ops.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_admin_circuit_api.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_circuit_breaker_fallback.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_circuit_breaker.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/api/__init__.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_usage_collector.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_circuit_probe.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/__init__.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_celery_routing.py
-->

---
### Requirement: Error classifier categorises exceptions as permanent or transient

The backend SHALL provide a service `app.services.error_classifier` exposing `classify(exc) -> Literal['permanent', 'transient', 'unknown']`. The classifier SHALL recognise as `permanent`:

- HTTP responses with status 401, 402, 403, 415, 422
- HTTP 400 responses whose body contains any of: `context_length_exceeded`, `invalid_api_key`, `insufficient_quota`
- Celery exceptions: `celery.exceptions.NotRegistered`, `kombu.exceptions.MessageStateError`
- Custom exceptions: `app.services.exceptions.InvalidProviderConfigError`, `app.services.exceptions.PromptTooLongError`

All other exceptions SHALL be classified as `transient`. If classification cannot proceed (unexpected exception structure), the result SHALL be `unknown` and SHALL be treated as `transient` for retry purposes.

#### Scenario: HTTP 402 classified permanent

- **WHEN** `classify(httpx.HTTPStatusError(response=Response(status_code=402)))` is called
- **THEN** the return value SHALL be `'permanent'`

#### Scenario: HTTP 429 rate limit classified transient

- **WHEN** `classify(httpx.HTTPStatusError(response=Response(status_code=429)))` is called
- **THEN** the return value SHALL be `'transient'`

#### Scenario: Network timeout classified transient

- **WHEN** `classify(httpx.TimeoutException("read timeout"))` is called
- **THEN** the return value SHALL be `'transient'`

#### Scenario: TaskNotRegistered classified permanent

- **WHEN** `classify(celery.exceptions.NotRegistered("app.workers.foo"))` is called
- **THEN** the return value SHALL be `'permanent'`

##### Example: classification table

| Exception | Result |
| --------- | ------ |
| `HTTPStatusError(401)` | permanent |
| `HTTPStatusError(402)` | permanent |
| `HTTPStatusError(415)` | permanent |
| `HTTPStatusError(400, body="context_length_exceeded")` | permanent |
| `HTTPStatusError(400, body="bad request")` | transient |
| `HTTPStatusError(429)` | transient |
| `HTTPStatusError(503)` | transient |
| `httpx.TimeoutException` | transient |
| `celery.exceptions.NotRegistered` | permanent |
| `KeyError("missing")` | unknown (treated as transient) |


<!-- @trace
source: task-failure-monitoring-and-circuit-breaker
updated: 2026-05-19
code:
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - .tmp/citation-unify-q3.png
  - .tmp/citation-unify-q1.png
  - backend/app/models/__init__.py
  - backend/app/api/query.py
  - src/releaseLog.jsx
  - backend/app/services/exceptions.py
  - backend/app/services/failure_log.py
  - backend/app/schemas/query.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - backend/app/main.py
  - backend/app/api/admin_circuit.py
  - src/QueueTab.jsx
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/workers/failure_hooks.py
  - backend/app/schemas/query_entity.py
  - backend/app/workers/usage_alert.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - docs/roadmap.md
  - backend/app/api/admin/chunking_status.py
  - backend/app/workers/appeal_digest.py
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/schemas/episode_guests.py
  - backend/app/workers/circuit_probe.py
  - backend/app/models/account_appeal.py
  - backend/app/models/episode.py
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - src/Shared.jsx
  - backend/app/models/transcript_chunk.py
  - src/ServiceStatusTab.jsx
  - src/AdminTokenizerTab.jsx
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/eval/runners/run.py
  - backend/app/services/sync.py
  - backend/app/api/appeal.py
  - backend/app/api/shows.py
  - src/CitationEvidenceCollapse.jsx
  - src/ProviderUsageTab.jsx
  - src/App.jsx
  - src/AdminPage.jsx
  - backend/alembic/versions/a5b6c7d8e9f0_add_task_failure_log_and_circuit_state.py
  - backend/app/workers/eval_reminder.py
  - backend/app/models/task_failure_log.py
  - src/AppealModal.jsx
  - backend/scripts/pilot_reembed_descriptions.py
  - docs/ai-steps.md
  - backend/app/services/zsend.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/errors.py
  - backend/app/services/citation_parser.py
  - src/QueryPage.jsx
  - backend/app/services/episode_finders.py
  - backend/app/services/circuit_breaker.py
  - backend/app/workers/tasks.py
  - backend/app/models/transcription_queue.py
  - .tmp/citation-unify-q2.png
  - .tmp/citation-unify-zh-all.png
  - CLAUDE.md
  - backend/eval/scripts/validate_schema.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/workers/dispatcher.py
  - backend/app/models/service_circuit_state.py
  - backend/app/services/provider_usage/__init__.py
  - backend/app/services/embedding.py
  - src/TranscriptPage.jsx
  - backend/app/services/transcription/openai_provider.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - backend/app/workers/failure_alert.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/summary_ops.py
  - backend/eval/datasets/README.md
  - backend/app/workers/lifecycle.py
  - backend/app/workers/quota_digest.py
  - backend/app/workers/topic_task.py
  - entrypoint.sh
  - backend/scripts/backfill_guests.py
  - backend/app/services/tokenizer.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/description_rechunker.py
  - backend/app/api/auth.py
  - backend/eval/metrics/recall.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - backend/app/workers/celery_app.py
  - backend/app/services/key_resolver.py
  - backend/app/api/admin/__init__.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/schemas/appeal.py
  - backend/app/services/rag.py
  - backend/app/services/rss_parser.py
  - backend/eval/datasets/_pending_review.json
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/core/csrf.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/services/error_classifier.py
  - backend/.env.example
  - backend/app/models/episode_description_chunk.py
  - backend/app/core/config.py
  - docs/celery-queues.md
  - backend/app/workers/summary_task.py
  - backend/app/models/ai_step.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/api/admin_provider_usage.py
  - backend/scripts/backfill_title_tsv.py
  - index.html
  - backend/app/api/admin_processing_stats.py
  - backend/app/workers/usage_collector.py
  - backend/app/services/description_indexer.py
tests:
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_error_classifier.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_failure_alert.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_admin_summary_ops.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_admin_circuit_api.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_circuit_breaker_fallback.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_circuit_breaker.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/api/__init__.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_usage_collector.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_circuit_probe.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/__init__.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_celery_routing.py
-->

---
### Requirement: Permanent errors short-circuit Celery retry

When a Celery task raises an exception that the error classifier returns as `permanent`, the task SHALL NOT use Celery's `autoretry_for` retry path. Instead the task's exception handler SHALL:

1. Call `error_classifier.classify(exc)` first.
2. If permanent → write a `task_failure_log` row with `failure_type='permanent'`, `retry_count=<current task.request.retries>`, then re-raise WITHOUT calling `self.retry(...)`.
3. If transient or unknown → fall through to existing `autoretry_for` behaviour (Celery handles retry).

The `tasks.py` / `topic_task.py` / `summary_task.py` task definitions SHALL implement this short-circuit. Other tasks (quota_digest / eval_reminder / db_backup) MAY adopt it as appropriate but SHALL at minimum write to `task_failure_log` on final failure.

#### Scenario: Permanent error skips retry

- **GIVEN** a `transcribe_episode` task with `task.request.retries == 0`
- **WHEN** the task raises `HTTPStatusError(402)` (permanent)
- **THEN** Celery SHALL NOT retry the task
- **AND** one row SHALL be written to `task_failure_log` with `retry_count=0`
- **AND** the task's status in Celery result backend SHALL be `FAILURE`

#### Scenario: Transient error follows existing retry path

- **GIVEN** a `transcribe_episode` task with `task.request.retries == 0`
- **WHEN** the task raises `httpx.TimeoutException`
- **THEN** Celery SHALL retry the task per existing `autoretry_for` config
- **AND** no row SHALL be written to `task_failure_log` until retries are exhausted


<!-- @trace
source: task-failure-monitoring-and-circuit-breaker
updated: 2026-05-19
code:
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - .tmp/citation-unify-q3.png
  - .tmp/citation-unify-q1.png
  - backend/app/models/__init__.py
  - backend/app/api/query.py
  - src/releaseLog.jsx
  - backend/app/services/exceptions.py
  - backend/app/services/failure_log.py
  - backend/app/schemas/query.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - backend/app/main.py
  - backend/app/api/admin_circuit.py
  - src/QueueTab.jsx
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/workers/failure_hooks.py
  - backend/app/schemas/query_entity.py
  - backend/app/workers/usage_alert.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - docs/roadmap.md
  - backend/app/api/admin/chunking_status.py
  - backend/app/workers/appeal_digest.py
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/schemas/episode_guests.py
  - backend/app/workers/circuit_probe.py
  - backend/app/models/account_appeal.py
  - backend/app/models/episode.py
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - src/Shared.jsx
  - backend/app/models/transcript_chunk.py
  - src/ServiceStatusTab.jsx
  - src/AdminTokenizerTab.jsx
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/eval/runners/run.py
  - backend/app/services/sync.py
  - backend/app/api/appeal.py
  - backend/app/api/shows.py
  - src/CitationEvidenceCollapse.jsx
  - src/ProviderUsageTab.jsx
  - src/App.jsx
  - src/AdminPage.jsx
  - backend/alembic/versions/a5b6c7d8e9f0_add_task_failure_log_and_circuit_state.py
  - backend/app/workers/eval_reminder.py
  - backend/app/models/task_failure_log.py
  - src/AppealModal.jsx
  - backend/scripts/pilot_reembed_descriptions.py
  - docs/ai-steps.md
  - backend/app/services/zsend.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/errors.py
  - backend/app/services/citation_parser.py
  - src/QueryPage.jsx
  - backend/app/services/episode_finders.py
  - backend/app/services/circuit_breaker.py
  - backend/app/workers/tasks.py
  - backend/app/models/transcription_queue.py
  - .tmp/citation-unify-q2.png
  - .tmp/citation-unify-zh-all.png
  - CLAUDE.md
  - backend/eval/scripts/validate_schema.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/workers/dispatcher.py
  - backend/app/models/service_circuit_state.py
  - backend/app/services/provider_usage/__init__.py
  - backend/app/services/embedding.py
  - src/TranscriptPage.jsx
  - backend/app/services/transcription/openai_provider.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - backend/app/workers/failure_alert.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/summary_ops.py
  - backend/eval/datasets/README.md
  - backend/app/workers/lifecycle.py
  - backend/app/workers/quota_digest.py
  - backend/app/workers/topic_task.py
  - entrypoint.sh
  - backend/scripts/backfill_guests.py
  - backend/app/services/tokenizer.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/description_rechunker.py
  - backend/app/api/auth.py
  - backend/eval/metrics/recall.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - backend/app/workers/celery_app.py
  - backend/app/services/key_resolver.py
  - backend/app/api/admin/__init__.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/schemas/appeal.py
  - backend/app/services/rag.py
  - backend/app/services/rss_parser.py
  - backend/eval/datasets/_pending_review.json
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/core/csrf.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/services/error_classifier.py
  - backend/.env.example
  - backend/app/models/episode_description_chunk.py
  - backend/app/core/config.py
  - docs/celery-queues.md
  - backend/app/workers/summary_task.py
  - backend/app/models/ai_step.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/api/admin_provider_usage.py
  - backend/scripts/backfill_title_tsv.py
  - index.html
  - backend/app/api/admin_processing_stats.py
  - backend/app/workers/usage_collector.py
  - backend/app/services/description_indexer.py
tests:
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_error_classifier.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_failure_alert.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_admin_summary_ops.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_admin_circuit_api.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_circuit_breaker_fallback.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_circuit_breaker.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/api/__init__.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_usage_collector.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_circuit_probe.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/__init__.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_celery_routing.py
-->

---
### Requirement: Sliding-window failure rate alert

The backend SHALL register a Celery Beat schedule entry `failure-alert` running every 5 minutes (cron `*/5 * * * *`). The handler SHALL:

1. SELECT each `task_name` having `COUNT(*) >= 3` rows in `task_failure_log` where `failed_at > NOW() - INTERVAL '30 minutes'` AND `alerted_at IS NULL`.
2. For each such `task_name`, send a ZSend email to `settings.zsend_admin_to_email` containing: task name, failure count in window, last 3 error_messages (truncated to 200 chars each), failed_at timestamps in Asia/Taipei timezone, count grouped by provider_id.
3. Update `alerted_at = NOW()` for the rows included in the alert (so they are not re-alerted).

If the ZSend send call fails (transient), the rows SHALL NOT be marked alerted; the next 5-min tick will retry. If ZSend is not configured (`settings.zsend_api_key is None`), the handler SHALL log "ZSend not configured, skipping alert" and SHALL NOT mark rows alerted.

#### Scenario: 3 failures in 30 minutes triggers email

- **GIVEN** `task_failure_log` has 3 rows for `transcribe_episode` with `failed_at` within the last 30 minutes and `alerted_at IS NULL`
- **WHEN** the failure-alert beat task runs
- **THEN** exactly one ZSend email SHALL be sent
- **AND** the 3 rows SHALL have `alerted_at = NOW()`

#### Scenario: 2 failures does not trigger

- **GIVEN** `task_failure_log` has 2 rows for `transcribe_episode` within 30 minutes
- **WHEN** the failure-alert beat task runs
- **THEN** no email SHALL be sent
- **AND** the 2 rows SHALL retain `alerted_at IS NULL`

#### Scenario: Already-alerted rows not re-alerted

- **GIVEN** 3 rows for `transcribe_episode` already have `alerted_at = NOW() - 10 minutes`
- **WHEN** the failure-alert beat task runs
- **THEN** no email SHALL be sent

#### Scenario: ZSend send failure leaves rows un-alerted for retry

- **GIVEN** 3 qualifying rows exist and the ZSend HTTP call raises `httpx.TimeoutException`
- **WHEN** the failure-alert beat task runs
- **THEN** the 3 rows SHALL retain `alerted_at IS NULL`
- **AND** the next failure-alert tick SHALL re-attempt the email

#### Scenario: ZSend not configured logs and skips

- **GIVEN** `settings.zsend_api_key is None` and 3 qualifying rows exist
- **WHEN** the failure-alert beat task runs
- **THEN** the handler SHALL log a warning "ZSend not configured, skipping alert"
- **AND** the 3 rows SHALL retain `alerted_at IS NULL`
- **AND** no email SHALL be sent

<!-- @trace
source: task-failure-monitoring-and-circuit-breaker
updated: 2026-05-19
code:
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - .tmp/citation-unify-q3.png
  - .tmp/citation-unify-q1.png
  - backend/app/models/__init__.py
  - backend/app/api/query.py
  - src/releaseLog.jsx
  - backend/app/services/exceptions.py
  - backend/app/services/failure_log.py
  - backend/app/schemas/query.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - backend/app/main.py
  - backend/app/api/admin_circuit.py
  - src/QueueTab.jsx
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/workers/failure_hooks.py
  - backend/app/schemas/query_entity.py
  - backend/app/workers/usage_alert.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - docs/roadmap.md
  - backend/app/api/admin/chunking_status.py
  - backend/app/workers/appeal_digest.py
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/schemas/episode_guests.py
  - backend/app/workers/circuit_probe.py
  - backend/app/models/account_appeal.py
  - backend/app/models/episode.py
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - src/Shared.jsx
  - backend/app/models/transcript_chunk.py
  - src/ServiceStatusTab.jsx
  - src/AdminTokenizerTab.jsx
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/eval/runners/run.py
  - backend/app/services/sync.py
  - backend/app/api/appeal.py
  - backend/app/api/shows.py
  - src/CitationEvidenceCollapse.jsx
  - src/ProviderUsageTab.jsx
  - src/App.jsx
  - src/AdminPage.jsx
  - backend/alembic/versions/a5b6c7d8e9f0_add_task_failure_log_and_circuit_state.py
  - backend/app/workers/eval_reminder.py
  - backend/app/models/task_failure_log.py
  - src/AppealModal.jsx
  - backend/scripts/pilot_reembed_descriptions.py
  - docs/ai-steps.md
  - backend/app/services/zsend.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/errors.py
  - backend/app/services/citation_parser.py
  - src/QueryPage.jsx
  - backend/app/services/episode_finders.py
  - backend/app/services/circuit_breaker.py
  - backend/app/workers/tasks.py
  - backend/app/models/transcription_queue.py
  - .tmp/citation-unify-q2.png
  - .tmp/citation-unify-zh-all.png
  - CLAUDE.md
  - backend/eval/scripts/validate_schema.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/workers/dispatcher.py
  - backend/app/models/service_circuit_state.py
  - backend/app/services/provider_usage/__init__.py
  - backend/app/services/embedding.py
  - src/TranscriptPage.jsx
  - backend/app/services/transcription/openai_provider.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - backend/app/workers/failure_alert.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/summary_ops.py
  - backend/eval/datasets/README.md
  - backend/app/workers/lifecycle.py
  - backend/app/workers/quota_digest.py
  - backend/app/workers/topic_task.py
  - entrypoint.sh
  - backend/scripts/backfill_guests.py
  - backend/app/services/tokenizer.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/description_rechunker.py
  - backend/app/api/auth.py
  - backend/eval/metrics/recall.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - backend/app/workers/celery_app.py
  - backend/app/services/key_resolver.py
  - backend/app/api/admin/__init__.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/schemas/appeal.py
  - backend/app/services/rag.py
  - backend/app/services/rss_parser.py
  - backend/eval/datasets/_pending_review.json
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/core/csrf.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/services/error_classifier.py
  - backend/.env.example
  - backend/app/models/episode_description_chunk.py
  - backend/app/core/config.py
  - docs/celery-queues.md
  - backend/app/workers/summary_task.py
  - backend/app/models/ai_step.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/api/admin_provider_usage.py
  - backend/scripts/backfill_title_tsv.py
  - index.html
  - backend/app/api/admin_processing_stats.py
  - backend/app/workers/usage_collector.py
  - backend/app/services/description_indexer.py
tests:
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_error_classifier.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_failure_alert.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_admin_summary_ops.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_admin_circuit_api.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_circuit_breaker_fallback.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_circuit_breaker.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/api/__init__.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_usage_collector.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_circuit_probe.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/__init__.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_celery_routing.py
-->