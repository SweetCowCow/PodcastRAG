# transcription-queue Specification

## Purpose

TBD - created by archiving change 'db-driven-queue-and-real-cron'. Update Purpose after archive.

## Requirements

### Requirement: DB-backed transcription queue table

The backend SHALL maintain a `transcription_queue` table where each row represents one episode's transcription job. Columns SHALL include: `id` (UUID, PK), `episode_id` (UUID, FK to episodes), `show_id` (UUID, FK to shows), `status` (enum: `pending`, `running`, `completed`, `failed`, `cancelled`), `position` (integer, monotonically assigned at enqueue, used for FIFO ordering of pending rows), `enqueued_at` (timestamp UTC), `started_at` (nullable timestamp UTC), `finished_at` (nullable timestamp UTC), `error_message` (nullable text), `ignored` (boolean, default false), `whisper_model` (string, snapshot of the model selected when enqueued), `celery_task_id` (nullable string, max 64 chars, written by the worker when the task starts executing — used to support force-cancel via Celery `revoke`).

`(episode_id)` SHALL be UNIQUE — at most one queue row per episode at any time. Re-enqueueing an already-`completed` or `failed` episode SHALL be modelled as a `status` transition (back to `pending`) on the existing row, NOT as a new row. Re-enqueueing SHALL clear `celery_task_id` back to NULL.

#### Scenario: Enqueue an episode for the first time

- **WHEN** the dispatcher receives a request to enqueue episode E for show S with model `whisper-1`
- **AND** no queue row exists for episode E
- **THEN** the backend SHALL insert a new row with `episode_id=E`, `show_id=S`, `status=pending`, `position` set to `MAX(position) + 1`, `enqueued_at=now`, `whisper_model=whisper-1`, `ignored=false`, `celery_task_id=null`

#### Scenario: Re-enqueue a previously completed episode

- **WHEN** the dispatcher is asked to enqueue episode E and a queue row for E already exists with `status=completed`
- **THEN** the backend SHALL update the existing row: `status=pending`, `position=MAX(position) + 1`, `started_at=null`, `finished_at=null`, `error_message=null`, `celery_task_id=null`

##### Example: re-enqueue keeps the same row id

- **GIVEN** queue row `id=R1, episode_id=E, status=completed, position=3, celery_task_id=abc-123`
- **AND** current `MAX(position) = 50`
- **WHEN** episode E is re-enqueued
- **THEN** row `R1` is updated to `status=pending, position=51, celery_task_id=null` (NOT a new row R2)


<!-- @trace
source: parallel-transcription-and-force-cancel
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Dispatcher pops jobs from DB queue in FIFO order

The dispatcher worker SHALL repeatedly select the lowest-`position` row from `transcription_queue` where `status = pending` AND `ignored = false` AND `dispatched_at IS NULL` using `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1` semantics, and invoke `transcribe_episode(episode_id)` by sending a Celery task to the broker. In the same DB transaction (before the `send_task` call), the dispatcher SHALL set `dispatched_at = NOW()` on the selected row and commit. This guarantees that a subsequent dispatcher tick cannot re-select the same row, eliminating the dispatcher self-race where two consecutive ticks both send a task for the same pending episode. The dispatcher SHALL NOT update the row's `status`, `started_at`, or `celery_task_id` fields when sending the task; those three fields SHALL be set by the worker task entry. The dispatcher SHALL use Celery broker FIFO + message priority for ordering at the broker layer; per-show ordering at the dispatch layer is determined entirely by the `position` column.

The number of rows simultaneously in `status = running` SHALL NOT exceed `app_settings.max_concurrent_transcriptions`. When the limit is reached, the dispatcher SHALL wait until at least one row finishes (transitions out of `running`) before sending the next task. The dispatcher SHALL count rows whose `status='running'` for this cap (i.e., it counts only rows that the worker has actually picked up, not rows the dispatcher has merely sent to the broker).

#### Scenario: FIFO order respected

- **WHEN** queue has pending rows with positions `[5, 8, 11]`
- **AND** all three are not ignored
- **THEN** the dispatcher SHALL send Celery tasks for them in order `5, 8, 11`

#### Scenario: Concurrency limit respected

- **WHEN** `max_concurrent_transcriptions = 1` AND one row is in `status=running`
- **THEN** the dispatcher SHALL NOT send another task to the broker until the current running row reaches `completed`, `failed`, or `cancelled`

#### Scenario: Dispatcher does not pre-mark row as running

- **GIVEN** a row R1 with `status='pending'`, `started_at=NULL`, `celery_task_id=NULL`, `dispatched_at=NULL`
- **WHEN** the dispatcher sends a Celery task for R1
- **THEN** R1 SHALL still have `status='pending'`, `started_at=NULL`, `celery_task_id=NULL` immediately after the dispatcher returns
- **AND** R1 SHALL have `dispatched_at` populated with the dispatcher's timestamp
- **AND** R1's status SHALL transition to `running` only when a worker picks the task up and runs its idempotent entry

#### Scenario: Dispatcher second tick does not re-select an already-dispatched pending row

- **GIVEN** a row R5 with `status='pending'`, `dispatched_at = NOW() - 30 seconds` (set by the previous dispatcher tick)
- **AND** the worker has not yet started processing R5 (broker queue depth > 0)
- **WHEN** the next dispatcher tick runs
- **THEN** the dispatcher SHALL NOT select R5 (filter `dispatched_at IS NULL` excludes it)
- **AND** the dispatcher SHALL NOT send a second Celery task for R5's episode

#### Scenario: Two concurrent dispatcher instances do not double-dispatch the same row

- **GIVEN** two dispatcher processes D1 and D2 running simultaneously (e.g., during a rolling deploy)
- **AND** a row R6 with `status='pending'`, `dispatched_at=NULL` is the next candidate
- **WHEN** D1 and D2 both attempt to claim R6 in the same instant
- **THEN** exactly one of them SHALL acquire the row lock via `SELECT ... FOR UPDATE SKIP LOCKED`
- **AND** the other SHALL skip R6 and select the next candidate row
- **AND** R6 SHALL receive exactly one Celery task


<!-- @trace
source: celery-routing-and-dispatcher-fix
updated: 2026-05-18
code:
  - backend/app/api/admin/__init__.py
  - backend/app/workers/usage_alert.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/scripts/backfill_guests.py
  - backend/eval/scripts/embedding_bakeoff.py
  - src/Shared.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/api/query.py
  - backend/app/services/exceptions.py
  - backend/app/workers/appeal_digest.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/services/episode_finders.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/rag.py
  - src/App.jsx
  - src/releaseLog.jsx
  - backend/app/services/sync.py
  - backend/app/workers/lifecycle.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/transcription_queue.py
  - src/AdminEpisodeGuestsTab.jsx
  - src/QueueTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/api/admin/chunking_status.py
  - backend/app/schemas/episode_guests.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/schemas/appeal.py
  - backend/app/models/__init__.py
  - docs/ai-steps.md
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/scripts/backfill_title_tsv.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - backend/app/main.py
  - CLAUDE.md
  - backend/app/services/description_rechunker.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/services/key_resolver.py
  - backend/app/workers/topic_task.py
  - backend/eval/metrics/recall.py
  - .tmp/citation-unify-q2.png
  - backend/app/services/zsend.py
  - backend/app/services/rss_parser.py
  - backend/app/schemas/query.py
  - backend/app/services/description_indexer.py
  - backend/app/workers/dispatcher.py
  - index.html
  - backend/app/workers/celery_app.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/models/account_appeal.py
  - .tmp/citation-unify-q3.png
  - src/AdminTokenizerTab.jsx
  - backend/app/api/shows.py
  - src/ProviderUsageTab.jsx
  - src/AppealModal.jsx
  - backend/app/workers/usage_collector.py
  - backend/app/services/tokenizer.py
  - docs/celery-queues.md
  - backend/app/api/appeal.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - .tmp/citation-unify-q1.png
  - backend/app/services/citation_parser.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/query_entity.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - backend/app/api/admin_provider_usage.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/workers/tasks.py
  - backend/app/workers/summary_task.py
  - backend/app/services/embedding.py
  - backend/eval/datasets/README.md
  - backend/app/services/provider_usage/__init__.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - entrypoint.sh
  - backend/eval/scripts/build_golden_set.py
  - backend/app/schemas/errors.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - src/CitationEvidenceCollapse.jsx
  - backend/app/services/transcription/openai_provider.py
  - src/QueryPage.jsx
  - backend/app/models/ai_step.py
  - backend/app/api/auth.py
  - docs/roadmap.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/eval/datasets/_pending_review.json
  - backend/.env.example
  - backend/eval/runners/run.py
  - backend/app/models/episode.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/models/transcript_chunk.py
  - src/TranscriptPage.jsx
  - .tmp/citation-unify-zh-all.png
  - backend/app/core/csrf.py
tests:
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/services/__init__.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_celery_routing.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_citation_parser.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_auth_db.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/api/__init__.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_transcribe_task_celery_id.py
-->

---
### Requirement: Cancel pending row

The backend SHALL expose `POST /admin/queue/{queue_id}/cancel` that accepts an optional `force` query parameter (boolean, default false).

When `force=false` (or absent): the endpoint SHALL transition a row from `pending` to `cancelled` and SHALL return HTTP 409 Conflict for any other status (running, completed, failed, already-cancelled).

When `force=true`: the endpoint SHALL additionally accept rows with `status=running`. For a running row, the backend SHALL: (1) read `celery_task_id` from the row; (2) if non-null, call `celery_app.control.revoke(celery_task_id, terminate=True, signal='SIGTERM')`; (3) update the row to `status=cancelled`, `finished_at=now`, `error_message='Force cancelled by admin'`; (4) **always** release the global throttle slot keyed by the queue row id (`release_global_slot(str(queue_id))`), regardless of whether `celery_task_id` is null. The slot ownership key SHALL be the queue row id (not the celery task id) so that release works even when the row had no celery task id assigned.

For `status=completed`, `failed`, or already-`cancelled`, `force=true` SHALL still return HTTP 409 (force only escalates pending/running to cancelled — terminal states are immutable).

The response body for a successful force-cancel of a running row SHALL include `{"force_cancelled": true, "celery_task_id": <string or null>}`.

Cancelled rows SHALL remain in the table for history/audit but SHALL be skipped by the dispatcher.

#### Scenario: Cancel a pending row succeeds without force

- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel` for a row with `status=pending`
- **THEN** the backend SHALL update the row to `status=cancelled` and return HTTP 200

#### Scenario: Cancel a running row without force is rejected

- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel` (no `force` parameter or `force=false`) for a row with `status=running`
- **THEN** the backend SHALL return HTTP 409 with body explaining that running jobs require force-cancel

#### Scenario: Force-cancel a running row revokes Celery task and releases slot

- **GIVEN** a queue row `R` with `status=running`, `celery_task_id='abc-123'`, and `acquire_global_slot(str(R.id))` was previously called raising the throttle counter to 1
- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel?force=true`
- **THEN** the backend SHALL call `celery_app.control.revoke('abc-123', terminate=True, signal='SIGTERM')`
- **AND** SHALL update the row to `status=cancelled`, `finished_at=<now>`, `error_message='Force cancelled by admin'`
- **AND** SHALL call `release_global_slot(str(R.id))` (slot ownership key is the row id)
- **AND** the throttle counter SHALL become 0
- **AND** SHALL return HTTP 200 with body `{"force_cancelled": true, "celery_task_id": "abc-123"}`

#### Scenario: Force-cancel a running row with null celery_task_id still releases slot

- **GIVEN** a queue row `R` with `status=running`, `celery_task_id=null`, and `acquire_global_slot(str(R.id))` was previously called raising the throttle counter to 1
- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel?force=true`
- **THEN** the backend SHALL NOT call `revoke` (no task id to target)
- **AND** SHALL update the row to `status=cancelled`, `finished_at=<now>`, `error_message='Force cancelled by admin'`
- **AND** SHALL still call `release_global_slot(str(R.id))`
- **AND** the throttle counter SHALL become 0
- **AND** SHALL return HTTP 200 with body `{"force_cancelled": true, "celery_task_id": null}`

#### Scenario: Force-cancel a completed row is rejected

- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel?force=true` for a row with `status=completed`
- **THEN** the backend SHALL return HTTP 409 — terminal states cannot be force-cancelled


<!-- @trace
source: deploy-resilience
updated: 2026-05-03
code:
  - backend/app/main.py
  - backend/app/workers/cron_tick.py
  - backend/app/workers/throttle.py
  - backend/app/workers/celery_app.py
  - backend/app/workers/tasks.py
  - backend/app/workers/lifecycle.py
  - backend/app/api/queue.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/config.py
tests:
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_worker_lifecycle.py
  - backend/tests/test_web_service_env_validation.py
  - backend/tests/test_force_cancel_throttle.py
  - backend/tests/test_queue_cancel.py
-->

---
### Requirement: Mark row as ignored

The backend SHALL expose `POST /admin/queue/{queue_id}/ignore` that sets `ignored = true` on the target row regardless of current status. Ignored rows SHALL be permanently skipped by both the dispatcher and the cron tick (cron tick MUST NOT re-enqueue an episode whose queue row has `ignored = true`, even if its status is `failed`).

The backend SHALL also expose `POST /admin/queue/{queue_id}/unignore` that sets `ignored = false`.

#### Scenario: Ignored failed row is not retried

- **WHEN** queue row R has `status=failed` AND `ignored=true`
- **AND** the cron tick runs and detects new episode that matches row R's episode_id
- **THEN** the cron tick SHALL NOT modify row R and SHALL NOT enqueue a new row for that episode


<!-- @trace
source: db-driven-queue-and-real-cron
updated: 2026-04-28
code:
  - backend/requirements.txt
  - backend/app/workers/dispatcher.py
  - backend/app/workers/throttle.py
  - backend/app/api/schedules.py
  - backend/app/models/app_settings.py
  - backend/app/workers/celery_app.py
  - backend/app/workers/dispatch.py
  - backend/app/workers/cron_tick.py
  - backend/alembic/versions/g5b6c7d8e9f0_extend_show_schedule.py
  - backend/app/api/transcripts.py
  - backend/app/schemas/settings.py
  - Dockerfile
  - backend/app/models/transcription_queue.py
  - backend/app/main.py
  - backend/app/api/shows.py
  - backend/app/schemas/queue.py
  - backend/app/workers/tasks.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/services/settings_cache.py
  - backend/docker-compose.yml
  - backend/app/models/show_schedule.py
  - backend/alembic/versions/h6c7d8e9f0a1_add_app_settings.py
  - backend/app/models/__init__.py
  - backend/app/api/settings.py
  - backend/app/api/queue.py
  - backend/app/schemas/schedule.py
  - backend/alembic/versions/f4a5b6c7d8e9_add_transcription_queue.py
-->

---
### Requirement: Cancel pending and running rows when show is deleted

When a show is deleted via `DELETE /shows/{show_id}`, the backend SHALL transition all `transcription_queue` rows for that show whose status is `pending` to `cancelled` BEFORE the show row is removed. Rows with `status = running` SHALL be transitioned to `cancelled` as well; the in-flight Celery task is not interrupted (Whisper API call already in progress) but its later attempt to write back to the queue row SHALL detect the `cancelled` status and abort writing transcript artifacts.

After the show is deleted, all queue rows for that show SHALL be removed via FK CASCADE on `episode_id`.

#### Scenario: Show deletion cancels pending queue rows first

- **WHEN** show S has 5 pending queue rows AND `DELETE /shows/{show_id}` is called
- **THEN** before the show is deleted, all 5 rows SHALL be updated to `status=cancelled`
- **AND** after the show is deleted, all 5 rows SHALL be removed by CASCADE


<!-- @trace
source: db-driven-queue-and-real-cron
updated: 2026-04-28
code:
  - backend/requirements.txt
  - backend/app/workers/dispatcher.py
  - backend/app/workers/throttle.py
  - backend/app/api/schedules.py
  - backend/app/models/app_settings.py
  - backend/app/workers/celery_app.py
  - backend/app/workers/dispatch.py
  - backend/app/workers/cron_tick.py
  - backend/alembic/versions/g5b6c7d8e9f0_extend_show_schedule.py
  - backend/app/api/transcripts.py
  - backend/app/schemas/settings.py
  - Dockerfile
  - backend/app/models/transcription_queue.py
  - backend/app/main.py
  - backend/app/api/shows.py
  - backend/app/schemas/queue.py
  - backend/app/workers/tasks.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/services/settings_cache.py
  - backend/docker-compose.yml
  - backend/app/models/show_schedule.py
  - backend/alembic/versions/h6c7d8e9f0a1_add_app_settings.py
  - backend/app/models/__init__.py
  - backend/app/api/settings.py
  - backend/app/api/queue.py
  - backend/app/schemas/schedule.py
  - backend/alembic/versions/f4a5b6c7d8e9_add_transcription_queue.py
-->

---
### Requirement: transcribe_episode task writes outcome back to queue row

The existing `transcribe_episode` Celery task SHALL look up the queue row matching its `episode_id` at start, and as its first DB action SHALL update the row's `celery_task_id` to `self.request.id` (the Celery-assigned task id). It SHALL then check the row's current `status`: if already `cancelled` (force-cancelled before the worker started executing, or cancelled by show deletion), the task SHALL exit silently without acquiring the global slot or processing the audio. Otherwise it SHALL set `started_at = now` if not already set and proceed.

At end the task SHALL set `status = completed` and `finished_at = now` on success, or `status = failed`, `error_message = <truncated message>`, `finished_at = now` on permanent failure. On retryable transient failure, the row's `status` SHALL remain `running` (the Celery task itself retries internally).

If at the end of the task the queue row's `status` is `cancelled` (because the show was deleted mid-task or force-cancel arrived during execution), the task SHALL NOT write any transcript or chunk records, SHALL NOT overwrite the row's `status`, and SHALL exit silently.

#### Scenario: Worker writes celery_task_id at task start

- **WHEN** `transcribe_episode(E)` begins execution with `self.request.id = 'task-abc-123'`
- **THEN** before any other DB write or audio processing, the task SHALL update the queue row for E to `celery_task_id='task-abc-123'` and commit

#### Scenario: Successful transcription updates queue row

- **WHEN** `transcribe_episode(E)` completes successfully
- **THEN** the queue row for E SHALL have `status=completed`, `finished_at` set to a timestamp ≥ `started_at`, `error_message=null`, and `celery_task_id` retained (not cleared)

#### Scenario: Permanent failure records error message

- **WHEN** `transcribe_episode(E)` raises a permanent error (e.g. `RssParseError`, `StorageError`)
- **THEN** the queue row SHALL have `status=failed`, `error_message` populated with the truncated exception text (max 2000 chars), `finished_at` set, and `celery_task_id` retained

#### Scenario: Mid-task force-cancel preserves cancelled status

- **WHEN** `transcribe_episode(E)` is interrupted by SIGTERM from a force-cancel revoke
- **AND** the queue row's `status` was set to `cancelled` by the cancel endpoint
- **THEN** when the task's exception handler runs, it SHALL re-read the row's status, observe `cancelled`, and SHALL NOT overwrite it with `failed`

#### Scenario: Force-cancel arrives before worker starts

- **WHEN** the queue row is set to `cancelled` by the cancel endpoint while the task message is still in the broker queue
- **AND** the worker subsequently picks up the task
- **THEN** the worker SHALL update `celery_task_id`, observe `status=cancelled`, and exit without processing audio or writing artifacts


<!-- @trace
source: parallel-transcription-and-force-cancel
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Global app_settings table for runtime configuration

The backend SHALL maintain an `app_settings` singleton table (one row enforced by application logic) with columns `max_concurrent_transcriptions` (integer, valid range 1–3 inclusive, default 1) and `monthly_cost_cap_usd` (numeric(10,2), nullable, default null, **reserved for future enforcement — not consumed by this change**). The dispatcher and `acquire_global_slot` SHALL read `max_concurrent_transcriptions` from this table on each enqueue/pop decision (or via a short-TTL cache, max 60 seconds).

#### Scenario: Concurrency change takes effect

- **WHEN** `max_concurrent_transcriptions` is updated from 1 to 3 in `app_settings`
- **AND** at most 60 seconds elapse
- **THEN** the dispatcher SHALL allow up to 3 rows in `status=running` simultaneously

#### Scenario: monthly_cost_cap_usd is not enforced in this change

- **WHEN** `monthly_cost_cap_usd` is set to any value (or null)
- **THEN** the dispatcher and cron tick SHALL behave identically — this field has no behavioural effect in this change

<!-- @trace
source: db-driven-queue-and-real-cron
updated: 2026-04-28
code:
  - backend/requirements.txt
  - backend/app/workers/dispatcher.py
  - backend/app/workers/throttle.py
  - backend/app/api/schedules.py
  - backend/app/models/app_settings.py
  - backend/app/workers/celery_app.py
  - backend/app/workers/dispatch.py
  - backend/app/workers/cron_tick.py
  - backend/alembic/versions/g5b6c7d8e9f0_extend_show_schedule.py
  - backend/app/api/transcripts.py
  - backend/app/schemas/settings.py
  - Dockerfile
  - backend/app/models/transcription_queue.py
  - backend/app/main.py
  - backend/app/api/shows.py
  - backend/app/schemas/queue.py
  - backend/app/workers/tasks.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/services/settings_cache.py
  - backend/docker-compose.yml
  - backend/app/models/show_schedule.py
  - backend/alembic/versions/h6c7d8e9f0a1_add_app_settings.py
  - backend/app/models/__init__.py
  - backend/app/api/settings.py
  - backend/app/api/queue.py
  - backend/app/schemas/schedule.py
  - backend/alembic/versions/f4a5b6c7d8e9_add_transcription_queue.py
-->

---
### Requirement: Reorder pending row position

The backend SHALL expose `PATCH /admin/queue/{queue_id}/position` accepting body `{"position": <int>}`. The endpoint SHALL only accept rows with `status=pending`; for any other status the endpoint SHALL return HTTP 409 Conflict.

The endpoint SHALL clamp the requested position to the valid range `[min(pending.position), max(pending.position)]` (inclusive). After clamping, the endpoint SHALL recompute pending row positions in a single transaction:

- If the clamped new position is less than the row's current position (move-forward), all pending rows whose position is in `[new_pos, old_pos)` SHALL have their position incremented by 1, and the target row's position SHALL be set to new_pos.
- If the clamped new position is greater than the row's current position (move-backward), all pending rows whose position is in `(old_pos, new_pos]` SHALL have their position decremented by 1, and the target row's position SHALL be set to new_pos.
- If the clamped new position equals the row's current position, the endpoint SHALL be a no-op and SHALL still return HTTP 200.

Only rows with `status=pending` SHALL be touched by the recompute; rows with other statuses SHALL retain their position values.

The endpoint SHALL return the updated target row as `QueueRowOut` on HTTP 200.

#### Scenario: Move pending row forward

- **GIVEN** pending rows ordered by position: `A(pos=10), B(pos=11), C(pos=12)`
- **WHEN** a client calls `PATCH /admin/queue/C.id/position` with body `{"position": 10}`
- **THEN** in one transaction A SHALL become position=11, B SHALL become position=12, C SHALL become position=10
- **AND** the response SHALL be HTTP 200 with C's updated row body

#### Scenario: Move pending row backward

- **GIVEN** pending rows ordered by position: `A(pos=10), B(pos=11), C(pos=12)`
- **WHEN** a client calls `PATCH /admin/queue/A.id/position` with body `{"position": 12}`
- **THEN** B SHALL become position=10, C SHALL become position=11, A SHALL become position=12
- **AND** the response SHALL be HTTP 200

#### Scenario: Position out of range is clamped

- **GIVEN** pending rows have positions `[10, 11, 12]`
- **WHEN** a client calls `PATCH /admin/queue/{id}/position` with body `{"position": 999}`
- **THEN** the position SHALL be clamped to 12 (max of pending)
- **AND** the move-backward recompute SHALL apply
- **AND** the response SHALL be HTTP 200

#### Scenario: Reordering a non-pending row is rejected

- **WHEN** a client calls `PATCH /admin/queue/{id}/position` for a row with `status=running`
- **THEN** the backend SHALL return HTTP 409 Conflict
- **AND** no positions SHALL be modified

#### Scenario: No-op when target equals current

- **GIVEN** a pending row at position 11
- **WHEN** a client calls PATCH with `{"position": 11}`
- **THEN** no row positions SHALL change
- **AND** the response SHALL be HTTP 200

<!-- @trace
source: transcription-queue-and-schedule-ui
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - backend/app/schemas/queue.py
  - src/Shared.jsx
  - backend/app/api/queue.py
  - src/QueueTab.jsx
  - src/AdminPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
tests:
  - backend/tests/test_queue_reorder.py
-->

---
### Requirement: Stale running row detection

The `cron_tick` Celery Beat task SHALL include a stale running detection sub-routine that runs at the start of every tick (every minute) before schedule processing.

The sub-routine SHALL identify queue rows in `status=running` whose `started_at` is older than 30 minutes AND whose `celery_task_id` is either NULL or NOT in the union of `celery_app.control.inspect(timeout=5).active()` and `reserved()` task IDs collected from all workers. Such rows SHALL be considered stale.

For each stale row, the sub-routine SHALL update the row to `status=failed`, `finished_at=now`, `error_message='Stale task — worker message lost'`. If the row's `celery_task_id` is non-null, the sub-routine SHALL also call `release_global_slot(celery_task_id)` to free the Redis throttle slot.

If `celery_app.control.inspect()` raises an exception, returns empty active and reserved dicts (e.g., broker unreachable), or times out, the entire stale detection sub-routine SHALL log a warning and skip this tick. The cron_tick main flow (schedule processing) SHALL continue normally regardless of detection sub-routine outcome.

The 30-minute threshold SHALL be a fixed constant in code, not a configurable setting.

#### Scenario: Stale row with celery_task_id not in active list is marked failed

- **GIVEN** a queue row with `status=running`, `started_at = now - 45 minutes`, `celery_task_id='abc-123'`
- **AND** `celery_app.control.inspect().active()` returns `{'worker-1': []}` and `reserved()` returns `{'worker-1': []}`
- **WHEN** cron_tick fires
- **THEN** the row SHALL be updated to `status=failed`, `finished_at=<now>`, `error_message='Stale task — worker message lost'`
- **AND** `release_global_slot('abc-123')` SHALL be called

#### Scenario: Stale row with null celery_task_id is marked failed without release

- **GIVEN** a queue row with `status=running`, `started_at = now - 35 minutes`, `celery_task_id=null`
- **WHEN** cron_tick fires
- **THEN** the row SHALL be updated to `status=failed`, `finished_at=<now>`, `error_message='Stale task — worker message lost'`
- **AND** `release_global_slot()` SHALL NOT be called

#### Scenario: Running row with task_id in active list is preserved

- **GIVEN** a queue row with `status=running`, `started_at = now - 45 minutes`, `celery_task_id='xyz-789'`
- **AND** `celery_app.control.inspect().active()` returns `{'worker-1': [{'id': 'xyz-789'}]}`
- **WHEN** cron_tick fires
- **THEN** the row SHALL remain `status=running` unchanged
- **AND** `release_global_slot()` SHALL NOT be called

#### Scenario: Running row younger than 30 minutes is preserved

- **GIVEN** a queue row with `status=running`, `started_at = now - 10 minutes`, `celery_task_id=null`
- **WHEN** cron_tick fires
- **THEN** the row SHALL remain `status=running` unchanged regardless of inspect results

#### Scenario: Inspect returning empty for all workers is treated as failure and detection is skipped

- **GIVEN** queue rows with `status=running` exist where some are older than 30 minutes
- **AND** `celery_app.control.inspect().active()` returns empty dict `{}` AND `reserved()` returns empty dict `{}`
- **WHEN** cron_tick fires
- **THEN** the stale detection sub-routine SHALL log a warning and skip this tick
- **AND** no rows SHALL be updated to `status=failed` by detection
- **AND** the cron_tick main flow (schedule processing + enqueue) SHALL still run normally

#### Scenario: Inspect raising exception causes detection skip

- **GIVEN** any queue row state
- **AND** `celery_app.control.inspect()` raises an exception (e.g. broker connection error)
- **WHEN** cron_tick fires
- **THEN** the stale detection sub-routine SHALL log a warning and skip this tick
- **AND** the cron_tick main flow SHALL still run normally

<!-- @trace
source: stale-running-detection
updated: 2026-04-28
code:
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/workers/cron_tick.py
  - docs/case-studies/transcription-queue-discussion.md
tests:
  - backend/tests/test_cron_tick_stale.py
-->

---
### Requirement: Throttle slot ownership keyed by queue row id

The functions `acquire_global_slot` and `release_global_slot` defined in `app.workers.throttle` SHALL use the queue row id (string form of `transcription_queue.id` UUID) as the ownership key for per-slot Redis records (`GLOBAL_SLOT_KEY` template). All call sites — `app.workers.tasks.transcribe_episode`, `app.api.queue.cancel_queue_row`, the worker shutdown signal handler, and the worker startup self-recovery routine — SHALL pass `str(queue_row.id)` (not the celery task id) when acquiring or releasing slots. This eliminates the previous failure mode where `release_global_slot(None)` would skip releasing the counter when `celery_task_id` had not yet been written back from the worker.

#### Scenario: Acquire and release with row id are symmetric

- **GIVEN** a queue row `R` with id `R.id`
- **WHEN** `acquire_global_slot(str(R.id))` is called and returns true, then `release_global_slot(str(R.id))` is called
- **THEN** the `transcribe:global:active_count` counter SHALL be the same value before acquire and after release
- **AND** the per-slot key `transcribe:global:slot:<R.id>` SHALL no longer exist after release

#### Scenario: Release tolerates a key that was never acquired

- **WHEN** `release_global_slot('00000000-0000-0000-0000-000000000000')` is called and no `acquire_global_slot` had been issued for this key
- **THEN** the counter SHALL be decremented but clamped to a non-negative value (the existing clamp behaviour SHALL be preserved)
- **AND** no exception SHALL be raised

<!-- @trace
source: deploy-resilience
updated: 2026-05-02
-->

<!-- @trace
source: deploy-resilience
updated: 2026-05-03
code:
  - backend/app/main.py
  - backend/app/workers/cron_tick.py
  - backend/app/workers/throttle.py
  - backend/app/workers/celery_app.py
  - backend/app/workers/tasks.py
  - backend/app/workers/lifecycle.py
  - backend/app/api/queue.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/config.py
tests:
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_worker_lifecycle.py
  - backend/tests/test_web_service_env_validation.py
  - backend/tests/test_force_cancel_throttle.py
  - backend/tests/test_queue_cancel.py
-->

---
### Requirement: Worker task entry transitions queue row to running atomically

When the `transcribe_episode` Celery task starts execution on a worker, before any external I/O (Whisper call, transcript persist), the task SHALL execute an idempotent entry routine that:

1. Acquires a row-level lock on the matching `transcription_queue` row using `SELECT ... FOR UPDATE`.
2. Inspects the row's current `status` and `started_at`:
   - If `status='pending'` → update `status='running'`, `started_at=NOW()`, `celery_task_id=<this task id>`. Proceed with transcription.
   - If `status='running'` AND `started_at > NOW() - INTERVAL '5 minutes'` → log a warning containing the existing `celery_task_id` and the current task id, ack the message, and return without doing transcription work (treats the message as a duplicate).
   - If `status='running'` AND `started_at <= NOW() - INTERVAL '5 minutes'` → take ownership: update `started_at=NOW()`, `celery_task_id=<this task id>`, log a warning that an apparently stale running row was reclaimed. Proceed with transcription.
   - If `status` is `cancelled`, `completed`, `failed`, `ignored`, or any other terminal/excluded state → ack the message and return without doing transcription work.
3. Commits the lock release within the entry routine before any long-running work.

This entry routine SHALL run inside a single short DB transaction (target: under 50ms) and SHALL not call any external network service.

#### Scenario: Pending row is claimed and processed

- **GIVEN** a row R1 with `status='pending'`, `started_at=NULL`
- **WHEN** the worker picks up `transcribe_episode(R1.episode_id)` task with task id `T1`
- **THEN** the entry routine SHALL update R1 to `status='running'`, `started_at=NOW()`, `celery_task_id='T1'`
- **AND** the worker SHALL proceed to call the transcription provider

#### Scenario: Duplicate task within 5 minutes is acked and skipped

- **GIVEN** a row R2 with `status='running'`, `started_at = NOW() - 2 minutes`, `celery_task_id='T2-original'`
- **WHEN** the worker picks up a second task `T2-duplicate` for the same episode
- **THEN** the entry routine SHALL detect the live `running` state
- **AND** the worker SHALL ack `T2-duplicate` without calling the transcription provider
- **AND** R2's `started_at` and `celery_task_id` SHALL remain unchanged

#### Scenario: Stale running row beyond 5 minutes is reclaimed

- **GIVEN** a row R3 with `status='running'`, `started_at = NOW() - 12 minutes`, `celery_task_id='T3-ghost'` (the original task crashed without releasing)
- **WHEN** the worker picks up a fresh task `T3-new` for the same episode
- **THEN** the entry routine SHALL update R3 to `started_at=NOW()`, `celery_task_id='T3-new'`
- **AND** the worker SHALL proceed to call the transcription provider
- **AND** the routine SHALL log a warning naming both task ids

#### Scenario: Cancelled row is acked without work

- **GIVEN** a row R4 with `status='cancelled'`
- **WHEN** the worker picks up a previously-enqueued task `T4` for R4's episode
- **THEN** the entry routine SHALL ack `T4` without calling the transcription provider
- **AND** R4's `status` SHALL remain `cancelled`


<!-- @trace
source: celery-routing-and-dispatcher-fix
updated: 2026-05-18
code:
  - backend/app/api/admin/__init__.py
  - backend/app/workers/usage_alert.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/scripts/backfill_guests.py
  - backend/eval/scripts/embedding_bakeoff.py
  - src/Shared.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/api/query.py
  - backend/app/services/exceptions.py
  - backend/app/workers/appeal_digest.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/services/episode_finders.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/rag.py
  - src/App.jsx
  - src/releaseLog.jsx
  - backend/app/services/sync.py
  - backend/app/workers/lifecycle.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/transcription_queue.py
  - src/AdminEpisodeGuestsTab.jsx
  - src/QueueTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/api/admin/chunking_status.py
  - backend/app/schemas/episode_guests.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/schemas/appeal.py
  - backend/app/models/__init__.py
  - docs/ai-steps.md
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/scripts/backfill_title_tsv.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - backend/app/main.py
  - CLAUDE.md
  - backend/app/services/description_rechunker.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/services/key_resolver.py
  - backend/app/workers/topic_task.py
  - backend/eval/metrics/recall.py
  - .tmp/citation-unify-q2.png
  - backend/app/services/zsend.py
  - backend/app/services/rss_parser.py
  - backend/app/schemas/query.py
  - backend/app/services/description_indexer.py
  - backend/app/workers/dispatcher.py
  - index.html
  - backend/app/workers/celery_app.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/models/account_appeal.py
  - .tmp/citation-unify-q3.png
  - src/AdminTokenizerTab.jsx
  - backend/app/api/shows.py
  - src/ProviderUsageTab.jsx
  - src/AppealModal.jsx
  - backend/app/workers/usage_collector.py
  - backend/app/services/tokenizer.py
  - docs/celery-queues.md
  - backend/app/api/appeal.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - .tmp/citation-unify-q1.png
  - backend/app/services/citation_parser.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/query_entity.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - backend/app/api/admin_provider_usage.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/workers/tasks.py
  - backend/app/workers/summary_task.py
  - backend/app/services/embedding.py
  - backend/eval/datasets/README.md
  - backend/app/services/provider_usage/__init__.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - entrypoint.sh
  - backend/eval/scripts/build_golden_set.py
  - backend/app/schemas/errors.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - src/CitationEvidenceCollapse.jsx
  - backend/app/services/transcription/openai_provider.py
  - src/QueryPage.jsx
  - backend/app/models/ai_step.py
  - backend/app/api/auth.py
  - docs/roadmap.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/eval/datasets/_pending_review.json
  - backend/.env.example
  - backend/eval/runners/run.py
  - backend/app/models/episode.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/models/transcript_chunk.py
  - src/TranscriptPage.jsx
  - .tmp/citation-unify-zh-all.png
  - backend/app/core/csrf.py
tests:
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/services/__init__.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_celery_routing.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_citation_parser.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_auth_db.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/api/__init__.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_transcribe_task_celery_id.py
-->

---
### Requirement: Startup hook resets dispatcher-marked running rows to pending

When the backend service or worker service starts, before processing any new requests or tasks, the existing startup self-recovery routine SHALL also identify rows in either of two ambiguous states:

1. `status='running'` AND `started_at IS NULL` — the legacy state in which the previous dispatcher had not set `started_at` consistently or the row was orphaned by the migration cutover.
2. `status='pending'` AND `dispatched_at IS NOT NULL` AND `dispatched_at < NOW() - INTERVAL '5 minutes'` — the dispatcher set `dispatched_at` but the worker never picked up the task (dispatcher process crashed between commit and `send_task`, or broker dropped the message). The row is effectively stuck pending forever because the new dispatcher filter excludes `dispatched_at IS NOT NULL`.

Each such row SHALL be reset to `status='pending'`, `started_at=NULL`, `celery_task_id=NULL`, `dispatched_at=NULL`, `error_message=NULL` and SHALL have its global throttle slot released via `release_global_slot(<row_id_str>)`.

This requirement covers the deployment cutover from "dispatcher sets running" to "worker entry sets running" and SHALL remain in effect for any future state where a row's `status='running'` but its provenance is ambiguous (no `started_at`), or `status='pending'` but `dispatched_at` is stuck.

#### Scenario: Migration cutover row is reset on startup

- **GIVEN** a row R1 with `status='running'`, `started_at=NULL`, `celery_task_id=NULL` exists when the worker restarts
- **WHEN** the worker's startup self-recovery routine runs
- **THEN** R1 SHALL be updated to `status='pending'`, `error_message=NULL`
- **AND** `release_global_slot('<R1.id>')` SHALL be called

#### Scenario: Existing orphan-revert behaviour preserved

- **GIVEN** the existing orphan-revert requirement in this spec (queue rows where `celery_task_id` is not in `inspect().active() ∪ reserved()`)
- **WHEN** the new startup hook also runs
- **THEN** the existing orphan-revert SHALL run without conflict
- **AND** the same row SHALL not be reset twice in the same startup pass

#### Scenario: Stuck dispatched_at row is reset on startup

- **GIVEN** a row R7 with `status='pending'`, `dispatched_at = NOW() - 12 minutes`, `started_at=NULL` (dispatcher crashed before `send_task` completed, broker never received the task)
- **WHEN** the worker's startup self-recovery routine runs
- **THEN** R7 SHALL be updated to `status='pending'`, `dispatched_at=NULL`
- **AND** the next dispatcher tick SHALL be free to re-select R7


<!-- @trace
source: celery-routing-and-dispatcher-fix
updated: 2026-05-18
code:
  - backend/app/api/admin/__init__.py
  - backend/app/workers/usage_alert.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/scripts/backfill_guests.py
  - backend/eval/scripts/embedding_bakeoff.py
  - src/Shared.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/api/query.py
  - backend/app/services/exceptions.py
  - backend/app/workers/appeal_digest.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/services/episode_finders.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/rag.py
  - src/App.jsx
  - src/releaseLog.jsx
  - backend/app/services/sync.py
  - backend/app/workers/lifecycle.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/transcription_queue.py
  - src/AdminEpisodeGuestsTab.jsx
  - src/QueueTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/api/admin/chunking_status.py
  - backend/app/schemas/episode_guests.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/schemas/appeal.py
  - backend/app/models/__init__.py
  - docs/ai-steps.md
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/scripts/backfill_title_tsv.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - backend/app/main.py
  - CLAUDE.md
  - backend/app/services/description_rechunker.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/services/key_resolver.py
  - backend/app/workers/topic_task.py
  - backend/eval/metrics/recall.py
  - .tmp/citation-unify-q2.png
  - backend/app/services/zsend.py
  - backend/app/services/rss_parser.py
  - backend/app/schemas/query.py
  - backend/app/services/description_indexer.py
  - backend/app/workers/dispatcher.py
  - index.html
  - backend/app/workers/celery_app.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/models/account_appeal.py
  - .tmp/citation-unify-q3.png
  - src/AdminTokenizerTab.jsx
  - backend/app/api/shows.py
  - src/ProviderUsageTab.jsx
  - src/AppealModal.jsx
  - backend/app/workers/usage_collector.py
  - backend/app/services/tokenizer.py
  - docs/celery-queues.md
  - backend/app/api/appeal.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - .tmp/citation-unify-q1.png
  - backend/app/services/citation_parser.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/query_entity.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - backend/app/api/admin_provider_usage.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/workers/tasks.py
  - backend/app/workers/summary_task.py
  - backend/app/services/embedding.py
  - backend/eval/datasets/README.md
  - backend/app/services/provider_usage/__init__.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - entrypoint.sh
  - backend/eval/scripts/build_golden_set.py
  - backend/app/schemas/errors.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - src/CitationEvidenceCollapse.jsx
  - backend/app/services/transcription/openai_provider.py
  - src/QueryPage.jsx
  - backend/app/models/ai_step.py
  - backend/app/api/auth.py
  - docs/roadmap.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/eval/datasets/_pending_review.json
  - backend/.env.example
  - backend/eval/runners/run.py
  - backend/app/models/episode.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/models/transcript_chunk.py
  - src/TranscriptPage.jsx
  - .tmp/citation-unify-zh-all.png
  - backend/app/core/csrf.py
tests:
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/services/__init__.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_celery_routing.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_citation_parser.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_auth_db.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/api/__init__.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_transcribe_task_celery_id.py
-->

---
### Requirement: Worker entry and terminal transitions clear dispatched_at

The worker task entry routine and all terminal state transitions (completed / failed / cancelled) SHALL clear `dispatched_at` to NULL alongside their existing field updates. This ensures the dispatcher filter `dispatched_at IS NULL` correctly identifies rows that are eligible for a fresh dispatch when retried, restarted, or re-enqueued.

#### Scenario: Worker entry clears dispatched_at when transitioning to running

- **GIVEN** a row R8 with `status='pending'`, `dispatched_at='2026-05-18 09:00:00'`
- **WHEN** the worker picks up the task and the entry routine transitions R8 to `status='running'`
- **THEN** R8 SHALL also have `dispatched_at=NULL` after the transition

#### Scenario: Terminal completion clears dispatched_at

- **GIVEN** a row R9 with `status='running'`, `dispatched_at=NULL` (already cleared by entry)
- **WHEN** the task completes and transitions R9 to `status='completed'`
- **THEN** R9 SHALL retain `dispatched_at=NULL`
- **AND** no later code path SHALL reintroduce a non-NULL `dispatched_at` to R9 without going through the dispatcher


<!-- @trace
source: celery-routing-and-dispatcher-fix
updated: 2026-05-18
code:
  - backend/app/api/admin/__init__.py
  - backend/app/workers/usage_alert.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/scripts/backfill_guests.py
  - backend/eval/scripts/embedding_bakeoff.py
  - src/Shared.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/api/query.py
  - backend/app/services/exceptions.py
  - backend/app/workers/appeal_digest.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/services/episode_finders.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/rag.py
  - src/App.jsx
  - src/releaseLog.jsx
  - backend/app/services/sync.py
  - backend/app/workers/lifecycle.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/transcription_queue.py
  - src/AdminEpisodeGuestsTab.jsx
  - src/QueueTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/api/admin/chunking_status.py
  - backend/app/schemas/episode_guests.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/schemas/appeal.py
  - backend/app/models/__init__.py
  - docs/ai-steps.md
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/scripts/backfill_title_tsv.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - backend/app/main.py
  - CLAUDE.md
  - backend/app/services/description_rechunker.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/services/key_resolver.py
  - backend/app/workers/topic_task.py
  - backend/eval/metrics/recall.py
  - .tmp/citation-unify-q2.png
  - backend/app/services/zsend.py
  - backend/app/services/rss_parser.py
  - backend/app/schemas/query.py
  - backend/app/services/description_indexer.py
  - backend/app/workers/dispatcher.py
  - index.html
  - backend/app/workers/celery_app.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/models/account_appeal.py
  - .tmp/citation-unify-q3.png
  - src/AdminTokenizerTab.jsx
  - backend/app/api/shows.py
  - src/ProviderUsageTab.jsx
  - src/AppealModal.jsx
  - backend/app/workers/usage_collector.py
  - backend/app/services/tokenizer.py
  - docs/celery-queues.md
  - backend/app/api/appeal.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - .tmp/citation-unify-q1.png
  - backend/app/services/citation_parser.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/query_entity.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - backend/app/api/admin_provider_usage.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/workers/tasks.py
  - backend/app/workers/summary_task.py
  - backend/app/services/embedding.py
  - backend/eval/datasets/README.md
  - backend/app/services/provider_usage/__init__.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - entrypoint.sh
  - backend/eval/scripts/build_golden_set.py
  - backend/app/schemas/errors.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - src/CitationEvidenceCollapse.jsx
  - backend/app/services/transcription/openai_provider.py
  - src/QueryPage.jsx
  - backend/app/models/ai_step.py
  - backend/app/api/auth.py
  - docs/roadmap.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/eval/datasets/_pending_review.json
  - backend/.env.example
  - backend/eval/runners/run.py
  - backend/app/models/episode.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/models/transcript_chunk.py
  - src/TranscriptPage.jsx
  - .tmp/citation-unify-zh-all.png
  - backend/app/core/csrf.py
tests:
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/services/__init__.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_celery_routing.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_citation_parser.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_auth_db.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/api/__init__.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_transcribe_task_celery_id.py
-->

---
### Requirement: transcription_queue schema includes dispatched_at column

The `transcription_queue` table SHALL include a `dispatched_at` column of type `TIMESTAMPTZ NULLABLE` with default NULL. The column SHALL be added via an Alembic migration. An index on `(status, dispatched_at)` partial-filtered to `WHERE status='pending'` SHALL be created to make the dispatcher's primary query `WHERE status='pending' AND dispatched_at IS NULL` index-only and fast.

#### Scenario: Migration adds the column with correct type and default

- **WHEN** the alembic migration is applied to a clean database
- **THEN** `\d transcription_queue` SHALL show the `dispatched_at TIMESTAMPTZ NULLABLE` column with default NULL
- **AND** the partial index on `(status, dispatched_at) WHERE status='pending'` SHALL exist

#### Scenario: Existing rows in production receive NULL value during migration

- **GIVEN** the migration is applied to a production DB with existing `transcription_queue` rows
- **WHEN** the migration completes
- **THEN** every pre-existing row SHALL have `dispatched_at=NULL` (treated as eligible for dispatch on the next tick)

<!-- @trace
source: celery-routing-and-dispatcher-fix
updated: 2026-05-18
code:
  - backend/app/api/admin/__init__.py
  - backend/app/workers/usage_alert.py
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/scripts/backfill_guests.py
  - backend/eval/scripts/embedding_bakeoff.py
  - src/Shared.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/api/query.py
  - backend/app/services/exceptions.py
  - backend/app/workers/appeal_digest.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/services/episode_finders.py
  - backend/eval/datasets/_schema.json
  - backend/app/services/rag.py
  - src/App.jsx
  - src/releaseLog.jsx
  - backend/app/services/sync.py
  - backend/app/workers/lifecycle.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/transcription_queue.py
  - src/AdminEpisodeGuestsTab.jsx
  - src/QueueTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/api/admin/chunking_status.py
  - backend/app/schemas/episode_guests.py
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/schemas/appeal.py
  - backend/app/models/__init__.py
  - docs/ai-steps.md
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/scripts/backfill_title_tsv.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/alembic/versions/z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - backend/app/main.py
  - CLAUDE.md
  - backend/app/services/description_rechunker.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/services/key_resolver.py
  - backend/app/workers/topic_task.py
  - backend/eval/metrics/recall.py
  - .tmp/citation-unify-q2.png
  - backend/app/services/zsend.py
  - backend/app/services/rss_parser.py
  - backend/app/schemas/query.py
  - backend/app/services/description_indexer.py
  - backend/app/workers/dispatcher.py
  - index.html
  - backend/app/workers/celery_app.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/models/account_appeal.py
  - .tmp/citation-unify-q3.png
  - src/AdminTokenizerTab.jsx
  - backend/app/api/shows.py
  - src/ProviderUsageTab.jsx
  - src/AppealModal.jsx
  - backend/app/workers/usage_collector.py
  - backend/app/services/tokenizer.py
  - docs/celery-queues.md
  - backend/app/api/appeal.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - .tmp/citation-unify-q1.png
  - backend/app/services/citation_parser.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/services/query_entity.py
  - backend/app/schemas/query_entity.py
  - backend/alembic/versions/y3f4a5b6c7d8_add_account_appeals.py
  - backend/app/api/admin_provider_usage.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/workers/tasks.py
  - backend/app/workers/summary_task.py
  - backend/app/services/embedding.py
  - backend/eval/datasets/README.md
  - backend/app/services/provider_usage/__init__.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - entrypoint.sh
  - backend/eval/scripts/build_golden_set.py
  - backend/app/schemas/errors.py
  - backend/app/services/provider_usage/zeabur_aihub_graphql.py
  - src/CitationEvidenceCollapse.jsx
  - backend/app/services/transcription/openai_provider.py
  - src/QueryPage.jsx
  - backend/app/models/ai_step.py
  - backend/app/api/auth.py
  - docs/roadmap.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/eval/datasets/_pending_review.json
  - backend/.env.example
  - backend/eval/runners/run.py
  - backend/app/models/episode.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/models/transcript_chunk.py
  - src/TranscriptPage.jsx
  - .tmp/citation-unify-zh-all.png
  - backend/app/core/csrf.py
tests:
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/services/__init__.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_dispatcher_idempotency.py
  - backend/tests/test_celery_routing.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_citation_parser.py
  - backend/tests/workers/__init__.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_auth_db.py
  - backend/tests/workers/test_appeal_digest.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/api/__init__.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/services/test_aihub_graphql_adapter.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/api/test_appeal.py
  - backend/tests/test_transcribe_task_celery_id.py
-->