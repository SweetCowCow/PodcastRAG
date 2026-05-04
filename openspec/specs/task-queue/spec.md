# task-queue Specification

## Purpose

TBD - created by archiving change 'transcription-pipeline'. Update Purpose after archive.

## Requirements

### Requirement: Celery application setup

The backend SHALL define a Celery application at `app.workers.celery_app` configured to use Redis as both broker and result backend, with `task_acks_late=True` and `worker_prefetch_multiplier=1`. The Celery application module SHALL also import `app.workers.lifecycle` so that the `worker_ready` and `worker_shutting_down` signal handlers (graceful shutdown + startup self-recovery) are registered when the worker process starts.

#### Scenario: Celery app boots

- **WHEN** the worker container starts with `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` both set to a reachable Redis instance
- **THEN** the Celery app SHALL import `app.workers.tasks` and `app.workers.lifecycle` at startup and register all declared tasks and signal handlers without errors

#### Scenario: Missing broker rejected

- **WHEN** the worker starts without `CELERY_BROKER_URL`
- **THEN** the process SHALL exit with a configuration error before accepting any task

#### Scenario: Lifecycle signals registered

- **WHEN** the Celery app is imported
- **THEN** at least one receiver SHALL be connected to `worker_ready` and at least one to `worker_shutting_down`


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
### Requirement: Redis service in docker-compose

The backend SHALL ship a `docker-compose.yml` definition that includes a `redis` service using an official Redis image, exposing the broker to the `backend` and `worker` services with a healthcheck.

#### Scenario: Compose stack starts

- **WHEN** `docker compose up` is run against the project compose file
- **THEN** `backend`, `worker`, `db`, and `redis` SHALL all report healthy within their configured healthchecks and the `worker` service SHALL wait for `redis` to be healthy before starting


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/docker-compose.yml
-->


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/alembic.ini
  - backend/app/workers/tasks.py
  - backend/app/services/transcription/factory.py
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/alembic/env.py
  - backend/app/models/episode.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/api/shows.py
  - backend/app/models/show.py
  - backend/app/services/rss_parser.py
  - backend/Dockerfile
  - backend/app/workers/celery_app.py
  - backend/.dockerignore
  - backend/.env.example
  - backend/app/api/transcripts.py
  - backend/app/workers/__init__.py
  - .spectra/spectra.db
  - backend/app/schemas/episode.py
  - backend/app/schemas/transcript.py
  - backend/app/models/transcript.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/schemas/sync.py
  - backend/app/main.py
  - backend/app/services/__init__.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/__init__.py
  - backend/app/services/transcription/openai_provider.py
  - backend/docker-compose.yml
  - backend/app/core/database.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/api/health.py
  - backend/alembic/script.py.mako
  - backend/app/services/transcription/base.py
  - backend/app/workers/dispatch.py
  - backend/app/services/transcription/__init__.py
  - backend/app/api/episodes.py
  - backend/requirements.txt
  - backend/app/core/__init__.py
-->

---
### Requirement: Worker service in docker-compose

The backend SHALL ship a `worker` service in `docker-compose.yml` that reuses the backend image with command `celery -A app.workers.celery_app worker --loglevel=info` and shares the same database and object-storage environment as the API container.

#### Scenario: Worker picks up task

- **WHEN** the `worker` service is running and an API request enqueues `transcribe_episode(episode_id)`
- **THEN** the worker SHALL log that it received the task within 5 seconds of enqueue and SHALL execute it without shared-state errors


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/docker-compose.yml
  - backend/Dockerfile
  - backend/app/workers/celery_app.py
  - backend/app/workers/tasks.py
-->


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/alembic.ini
  - backend/app/workers/tasks.py
  - backend/app/services/transcription/factory.py
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/alembic/env.py
  - backend/app/models/episode.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/api/shows.py
  - backend/app/models/show.py
  - backend/app/services/rss_parser.py
  - backend/Dockerfile
  - backend/app/workers/celery_app.py
  - backend/.dockerignore
  - backend/.env.example
  - backend/app/api/transcripts.py
  - backend/app/workers/__init__.py
  - .spectra/spectra.db
  - backend/app/schemas/episode.py
  - backend/app/schemas/transcript.py
  - backend/app/models/transcript.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/schemas/sync.py
  - backend/app/main.py
  - backend/app/services/__init__.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/__init__.py
  - backend/app/services/transcription/openai_provider.py
  - backend/docker-compose.yml
  - backend/app/core/database.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/api/health.py
  - backend/alembic/script.py.mako
  - backend/app/services/transcription/base.py
  - backend/app/workers/dispatch.py
  - backend/app/services/transcription/__init__.py
  - backend/app/api/episodes.py
  - backend/requirements.txt
  - backend/app/core/__init__.py
-->

---
### Requirement: Task dispatch helper

The backend SHALL expose a helper `enqueue_transcription(episode_id)` that API endpoints call to send the transcription task to the queue, ensuring the task name and argument signature stay consistent.

#### Scenario: API uses helper

- **WHEN** `POST /episodes/{id}/transcribe` handles a new request
- **THEN** it SHALL call `enqueue_transcription(episode_id)` exactly once per accepted request rather than invoking Celery `send_task` directly


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/app/workers/dispatch.py
  - backend/app/workers/celery_app.py
  - backend/app/api/transcripts.py
-->

<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/alembic.ini
  - backend/app/workers/tasks.py
  - backend/app/services/transcription/factory.py
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/alembic/env.py
  - backend/app/models/episode.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/api/shows.py
  - backend/app/models/show.py
  - backend/app/services/rss_parser.py
  - backend/Dockerfile
  - backend/app/workers/celery_app.py
  - backend/.dockerignore
  - backend/.env.example
  - backend/app/api/transcripts.py
  - backend/app/workers/__init__.py
  - .spectra/spectra.db
  - backend/app/schemas/episode.py
  - backend/app/schemas/transcript.py
  - backend/app/models/transcript.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/schemas/sync.py
  - backend/app/main.py
  - backend/app/services/__init__.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/__init__.py
  - backend/app/services/transcription/openai_provider.py
  - backend/docker-compose.yml
  - backend/app/core/database.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/api/health.py
  - backend/alembic/script.py.mako
  - backend/app/services/transcription/base.py
  - backend/app/workers/dispatch.py
  - backend/app/services/transcription/__init__.py
  - backend/app/api/episodes.py
  - backend/requirements.txt
  - backend/app/core/__init__.py
-->

---
### Requirement: Global concurrency semaphore bounds active transcriptions

The Celery `transcribe_episode` task SHALL enforce a cross-worker concurrency limit using a Redis-backed semaphore. The maximum number of simultaneously active transcriptions SHALL be configured by the `MAX_CONCURRENT_TRANSCRIPTIONS` environment variable, defaulting to `1`. When a task starts, it SHALL attempt to acquire a global slot by incrementing the Redis counter `transcribe:global:active_count`; if the incremented value exceeds the configured maximum, the task SHALL immediately decrement the counter back and requeue itself via `self.retry(countdown=15, max_retries=None)`. Successful or permanently failed tasks SHALL always decrement the counter in a `finally` block.

#### Scenario: Task runs when slot is available

- **WHEN** `MAX_CONCURRENT_TRANSCRIPTIONS=2` and 1 task is currently active
- **THEN** a newly-started task SHALL successfully acquire a slot and proceed with transcription

#### Scenario: Task requeues when limit reached

- **WHEN** `MAX_CONCURRENT_TRANSCRIPTIONS=1` and 1 task is currently active
- **THEN** a second task SHALL not proceed with transcription, SHALL decrement the counter back, and SHALL be requeued with a 15-second countdown

#### Scenario: Slot released on successful completion

- **WHEN** a task finishes transcription successfully
- **THEN** the counter `transcribe:global:active_count` SHALL be decremented by 1 before the task returns

#### Scenario: Slot released on permanent failure

- **WHEN** a task writes `transcript.status='failed'` due to a permanent error and returns
- **THEN** the counter `transcribe:global:active_count` SHALL still be decremented by 1


<!-- @trace
source: concurrency-control-and-retry
updated: 2026-04-25
code:
  - src/AdminPage.jsx
  - backend/app/api/admin.py
  - CLAUDE.md
  - backend/app/workers/tasks.py
  - backend/app/main.py
  - backend/requirements.txt
  - backend/app/workers/throttle.py
  - backend/app/schemas/admin.py
  - backend/app/services/transcription/openai_provider.py
  - backend/app/core/config.py
-->

---
### Requirement: Per-show exclusivity lock

The Celery `transcribe_episode` task SHALL acquire a per-show Redis lock at key `transcribe:show:{show_id}:lock` using `SET NX EX 1800` (30-minute TTL) before beginning transcription. If the lock is already held, the task SHALL release its global slot and requeue itself via `self.retry(countdown=60, max_retries=None)`. On task completion (success or permanent failure), the task SHALL delete the lock.

#### Scenario: Task proceeds when show is not locked

- **WHEN** a task starts for show A and no `transcribe:show:A:lock` key exists
- **THEN** the task SHALL set the lock with 30-minute TTL and proceed

#### Scenario: Task requeues when show is already locked

- **WHEN** a task starts for show A and a second task for the same show A is already running
- **THEN** the second task SHALL fail to acquire the lock, release its global slot, and requeue with a 60-second countdown

#### Scenario: Lock auto-expires after TTL

- **WHEN** a worker holding `transcribe:show:A:lock` crashes without releasing
- **THEN** the lock SHALL automatically expire after 30 minutes, allowing future tasks for show A to proceed

#### Scenario: Different shows run in parallel under the global limit

- **WHEN** `MAX_CONCURRENT_TRANSCRIPTIONS=2` and tasks for show A and show B start simultaneously
- **THEN** both tasks SHALL acquire their per-show locks independently and run in parallel


<!-- @trace
source: concurrency-control-and-retry
updated: 2026-04-25
code:
  - src/AdminPage.jsx
  - backend/app/api/admin.py
  - CLAUDE.md
  - backend/app/workers/tasks.py
  - backend/app/main.py
  - backend/requirements.txt
  - backend/app/workers/throttle.py
  - backend/app/schemas/admin.py
  - backend/app/services/transcription/openai_provider.py
  - backend/app/core/config.py
-->

---
### Requirement: Global slot key has a TTL safety net

When the task successfully acquires a global semaphore slot, it SHALL also `SET transcribe:global:slot:{task_id} 1 EX 7200` (2-hour TTL) as a side record of the slot holder. On release, the task SHALL delete both the side record and decrement the counter. The side record's TTL protects against permanent counter drift if the worker crashes between increment and finally-decrement.

#### Scenario: Side record created on acquire

- **WHEN** a task acquires a global slot
- **THEN** Redis SHALL contain a key `transcribe:global:slot:{task_id}` with a value and a TTL of at most 7200 seconds

#### Scenario: Side record deleted on release

- **WHEN** a task releases its global slot
- **THEN** the key `transcribe:global:slot:{task_id}` SHALL be deleted from Redis

<!-- @trace
source: concurrency-control-and-retry
updated: 2026-04-25
code:
  - src/AdminPage.jsx
  - backend/app/api/admin.py
  - CLAUDE.md
  - backend/app/workers/tasks.py
  - backend/app/main.py
  - backend/requirements.txt
  - backend/app/workers/throttle.py
  - backend/app/schemas/admin.py
  - backend/app/services/transcription/openai_provider.py
  - backend/app/core/config.py
-->

---
### Requirement: Worker service runs with concurrency 3 in production

In production deployments (Zeabur), the `worker` service SHALL run a Celery worker with `--concurrency=3` (single replica with 3 prefork worker processes, one task per process at a time). Real concurrent transcription capacity SHALL therefore be 3.

The dispatcher's logical cap (`app_settings.max_concurrent_transcriptions`, range 1–3) SHALL never exceed the worker concurrency. The system SHALL NOT attempt to auto-scale based on the setting; the concurrency value is a fixed deployment-level constant configured via the `START_COMMAND` environment variable on the worker service.

If a worker process crashes or is terminated, in-flight tasks SHALL rely on the existing stale-running detection (dispatcher's TTL-based throttle slot) and the queue's row-level status tracking for recovery. Celery prefork SHALL automatically respawn crashed worker processes within the same container.

#### Scenario: Worker concurrency 3 processes three tasks in parallel

- **GIVEN** worker service is running with `--concurrency=3` (single replica, 3 prefork processes)
- **AND** `app_settings.max_concurrent_transcriptions = 3`
- **WHEN** the dispatcher sends 3 transcribe_episode tasks to the broker
- **THEN** each prefork process SHALL pick up exactly one task within 5 seconds of dispatch
- **AND** all 3 tasks SHALL be in `running` simultaneously (started_at within a 10-second window)

#### Scenario: Setting cap below worker concurrency leaves processes idle

- **GIVEN** worker service is running with `--concurrency=3`
- **AND** `app_settings.max_concurrent_transcriptions = 1`
- **WHEN** 5 episodes are enqueued
- **THEN** the dispatcher SHALL dispatch tasks one at a time
- **AND** at most 1 prefork process SHALL be processing at any moment; the other 2 SHALL remain idle

<!-- @trace
source: parallel-transcription-and-force-cancel
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Worker reverts running rows to pending on graceful shutdown

The Celery worker SHALL register a `worker_shutting_down` signal handler that, when triggered (typically by SIGTERM during deploy), identifies all `transcription_queue` rows currently held by this worker (i.e., rows whose `id` matches an entry in `celery_app.control.inspect().active()` task arg list belonging to this worker, or rows whose `status='running'` and `celery_task_id` belongs to a task currently executing in this worker process). For each such row, the handler SHALL:

1. Update the row to `status='pending'`, `started_at=NULL`, `celery_task_id=NULL`, `error_message=NULL`.
2. Call `release_global_slot(<row_id_str>)` to free the throttle slot.

The handler SHALL complete within the worker's SIGTERM grace window (default 30 seconds). If the handler raises an exception, it SHALL log the failure and proceed; the worker startup self-recovery requirement covers the residual case.

#### Scenario: Graceful shutdown reverts a single running row

- **GIVEN** the worker is currently executing a `transcribe_episode` task for queue row `R1` (status=running, started_at=now-2min, celery_task_id='task-abc')
- **AND** `acquire_global_slot('<R1.id>')` was called and the throttle counter is 1
- **WHEN** the worker receives SIGTERM
- **THEN** the `worker_shutting_down` handler SHALL update row `R1` to `status='pending'`, `started_at=NULL`, `celery_task_id=NULL`
- **AND** `release_global_slot('<R1.id>')` SHALL be called
- **AND** the throttle counter SHALL become 0

#### Scenario: Graceful shutdown handler exception does not crash worker exit

- **GIVEN** the handler is registered and an unexpected exception is raised mid-routine (e.g., DB connection lost)
- **WHEN** the handler executes
- **THEN** the exception SHALL be logged
- **AND** the worker process SHALL still exit cleanly without re-raising

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
### Requirement: Worker reverts orphaned running rows to pending on startup

The Celery worker SHALL run a self-recovery routine immediately after `worker_ready` signal fires and before processing the first new task. The routine SHALL query `transcription_queue` for all rows where `status='running'`. For each such row, the worker SHALL determine if the row is orphaned by checking:

- If `celery_task_id IS NULL` → orphaned.
- If `celery_task_id` is set but NOT present in `celery_app.control.inspect(timeout=5).active()` union `reserved()` task IDs → orphaned.

For each orphaned row, the routine SHALL update the row to `status='pending'`, `started_at=NULL`, `celery_task_id=NULL`, `error_message=NULL` and call `release_global_slot(<row_id_str>)`. Rows whose `celery_task_id` is in the active/reserved set SHALL be left unchanged (covers the case of multiple worker replicas where another worker still owns the task).

If `celery_app.control.inspect()` raises, returns empty dicts, or times out, the routine SHALL be conservative: only rows with `celery_task_id IS NULL` are reverted; rows with non-null `celery_task_id` SHALL be left untouched and rely on stale-running-detection (30-min cron) as the next safety net.

#### Scenario: Orphan with NULL task id is reverted on startup

- **GIVEN** a queue row `R1` with `status='running'`, `started_at=now-3min`, `celery_task_id=NULL` exists in the database when the worker starts
- **WHEN** the worker's startup self-recovery routine runs
- **THEN** `R1` SHALL be updated to `status='pending'`, `started_at=NULL`, `error_message=NULL`
- **AND** `release_global_slot('<R1.id>')` SHALL be called

#### Scenario: Orphan with task id not in active list is reverted on startup

- **GIVEN** a queue row `R2` with `status='running'`, `celery_task_id='ghost-task'` and `inspect().active()` returns `{'worker-1': []}`, `reserved()` returns `{'worker-1': []}`
- **WHEN** the worker's startup self-recovery routine runs
- **THEN** `R2` SHALL be updated to `status='pending'`, `started_at=NULL`, `celery_task_id=NULL`

#### Scenario: Running row with active task is preserved on startup

- **GIVEN** a queue row `R3` with `status='running'`, `celery_task_id='live-task'` and `inspect().active()` returns `{'worker-1': [{'id': 'live-task'}]}`
- **WHEN** the worker's startup self-recovery routine runs
- **THEN** `R3` SHALL remain unchanged

#### Scenario: Inspect failure leaves non-null task id rows unchanged

- **GIVEN** a queue row `R4` with `status='running'`, `celery_task_id='unknown-task'` and `celery_app.control.inspect()` raises an exception
- **WHEN** the worker's startup self-recovery routine runs
- **THEN** `R4` SHALL remain unchanged
- **AND** the routine SHALL log a warning indicating inspect failed

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
### Requirement: Cron tick scans for stale-running summary tasks

The `cron_tick` Celery task (already runs once per minute via Celery Beat) SHALL invoke a new helper, `_detect_stale_summary_running(session_factory)`, after the existing transcription-queue stale-running detection. The helper SHALL select rows from `episodes` where `ai_summary_status='running'` AND `ai_summary_started_at IS NOT NULL` AND `ai_summary_started_at < now() - settings.summary_stale_threshold_seconds * INTERVAL '1 second'`. For each selected row, the helper SHALL:

1. UPDATE the row to `ai_summary_status='pending'`, `ai_summary_started_at=NULL`, `ai_summary_error='recovered from stale running after <N>s'` (where `<N>` is the elapsed seconds at detection time).
2. Call `generate_episode_summary.delay(<episode_id>)`.

If step 2 raises (e.g. broker unreachable), the helper SHALL roll back the row's UPDATE for that row only and continue processing the remaining stale rows. The helper SHALL log the total count of rows recovered (or zero, silently). Exceptions raised by the helper itself (e.g. SELECT failure) SHALL be caught by `cron_tick` so the rest of the tick (schedule refresh, transcription stale detection, orphan revert) continues running.

#### Scenario: Stale summary row is reset and re-enqueued

- **GIVEN** a row in `episodes` with `ai_summary_status='running'` and `ai_summary_started_at = now() - 700s`
- **AND** `summary_stale_threshold_seconds = 600`
- **WHEN** `_run_tick()` invokes `_detect_stale_summary_running(Session)`
- **THEN** the row SHALL be UPDATEd to `ai_summary_status='pending'`, `ai_summary_started_at IS NULL`, `ai_summary_error LIKE 'recovered from stale running after %'`
- **AND** `generate_episode_summary.delay(<episode_id>)` SHALL be called exactly once

#### Scenario: Multiple stale rows are processed in one tick

- **GIVEN** 3 rows with `ai_summary_status='running'` and `ai_summary_started_at` 700s, 800s, 900s in the past
- **WHEN** `_run_tick()` invokes `_detect_stale_summary_running(Session)`
- **THEN** all 3 rows SHALL be reset to `pending` and 3 Celery tasks SHALL be enqueued
- **AND** the helper SHALL log `"cron_tick: stale summary recovered: 3 rows"`

#### Scenario: Helper exception does not break the rest of the tick

- **GIVEN** the SELECT inside `_detect_stale_summary_running` raises a database error
- **WHEN** `_run_tick()` runs
- **THEN** the exception SHALL be caught and logged with `exc_info=True`
- **AND** the subsequent schedule-refresh logic in `_run_tick()` SHALL still execute

#### Scenario: Per-row enqueue failure does not poison the batch

- **GIVEN** 2 stale rows; the first `generate_episode_summary.delay()` call raises (e.g. broker unreachable) and the second succeeds
- **WHEN** `_detect_stale_summary_running` runs
- **THEN** the first row SHALL be rolled back to `ai_summary_status='running'` (its UPDATE undone)
- **AND** the second row SHALL be reset to `pending` and its task enqueued
- **AND** the helper SHALL log a warning naming the failed row id

<!-- @trace
source: summary-stale-detection
updated: 2026-05-04
code:
  - docs/research/competitive-feature-plan.md
  - backend/app/core/config.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/models/episode.py
  - backend/app/workers/cron_tick.py
  - backend/app/workers/summary_task.py
  - docs/research/competitive-analysis.md
  - backend/app/schemas/queue.py
  - backend/app/schemas/episode.py
  - backend/alembic/versions/o3d4e5f6a7b8_add_ai_summary_started_at_and_error.py
  - src/QueueTab.jsx
  - aisteps-tab.png
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - backend/app/api/queue.py
tests:
  - backend/tests/test_cron_tick_stale.py
  - backend/tests/test_summary_integration.py
  - backend/tests/test_config.py
-->