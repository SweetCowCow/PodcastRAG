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

---
### Requirement: Queue routing splits tasks across four named queues

The Celery application SHALL configure `task_routes` so that each task class is routed to one of four named queues based on its workload category:

- `transcribe` queue: `app.workers.tasks.transcribe_episode`
- `topic` queue: `app.workers.topic_task.classify_episode_topics`
- `summary` queue: `app.workers.summary_task.generate_episode_summary`
- `control` queue: cron_tick, quota_digest, eval_reminder, db_backup, tokenizer_reload, and any task without an explicit route

The `task_default_queue` SHALL be set to `control` so that tasks added in the future without an explicit `task_routes` entry are not silently dropped or sent to a queue that no worker is listening to.

#### Scenario: transcribe task routed to transcribe queue

- **WHEN** `transcribe_episode.delay(episode_id)` is called
- **THEN** the broker SHALL receive the task message on the queue named `transcribe`

#### Scenario: topic task routed to topic queue

- **WHEN** `classify_episode_topics.delay(episode_id)` is called
- **THEN** the broker SHALL receive the task message on the queue named `topic`

#### Scenario: unrouted task falls back to control queue

- **WHEN** a new task `app.workers.foo.bar` is registered with no entry in `task_routes` and `bar.delay()` is called
- **THEN** the broker SHALL receive the task message on the queue named `control`


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
### Requirement: Message priority orders task dispatch within and across queues

The Celery application SHALL set `task_queue_max_priority=10` and `task_default_priority=5`, and configure `broker_transport_options={"priority_steps": [0, 3, 6, 9]}` for the Redis broker. Each task SHALL declare a default priority value via its `apply_async`/`delay` configuration:

- `transcribe_episode`: priority `9` (highest)
- `classify_episode_topics`: priority `2`
- `generate_episode_summary`: priority `2`
- All other tasks: priority `5` (default)

When a worker process becomes idle, the Redis broker SHALL deliver the highest-priority pending message available across all subscribed queues before delivering any lower-priority message.

#### Scenario: high-priority transcribe preempts low-priority backfill

- **GIVEN** the worker has 6 prefork slots, 5 of which are currently running `classify_episode_topics` tasks (priority=2)
- **AND** 100 additional `classify_episode_topics` tasks are pending on the `topic` queue
- **AND** 1 `transcribe_episode` task (priority=9) is pending on the `transcribe` queue
- **WHEN** the next prefork slot becomes idle (current task completes)
- **THEN** the worker SHALL pick up the `transcribe_episode` task before any of the 100 pending `topic` tasks

##### Example: priority pop order

| Pending messages on broker | Next idle slot picks |
| -------------------------- | -------------------- |
| 50× topic (p=2) | 1× topic (p=2) |
| 50× topic (p=2), 1× transcribe (p=9) | 1× transcribe (p=9) |
| 1× control cron_tick (p=5), 50× topic (p=2) | 1× cron_tick (p=5) |
| 1× transcribe (p=9), 1× cron_tick (p=5), 1× topic (p=2) | 1× transcribe (p=9), then cron_tick, then topic |

#### Scenario: tasks within the same priority level use queue FIFO order

- **GIVEN** 10 `classify_episode_topics` tasks (priority=2) enqueued in order T1...T10
- **WHEN** a worker slot becomes idle
- **THEN** the worker SHALL pick up T1 before T2 (FIFO within the same priority bucket)


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
### Requirement: Worker subscribes to all four named queues

The Celery worker process SHALL be started with `--queues=transcribe,topic,summary,control` so that it consumes from all four routed queues. The Zeabur `worker` service `START_COMMAND` SHALL include this flag. The worker SHALL not be configured to listen exclusively to a subset (no per-queue worker split is introduced).

#### Scenario: Worker accepts task from any of the four queues

- **GIVEN** the worker is running with `--queues=transcribe,topic,summary,control`
- **WHEN** any task is dispatched to any one of the four queues
- **THEN** the worker SHALL receive and execute the task within 5 seconds of broker delivery (subject to concurrency slot availability)

#### Scenario: Worker without --queues flag rejects new queues

- **GIVEN** the worker `START_COMMAND` does not include `--queues`
- **WHEN** a `classify_episode_topics` task is dispatched to the `topic` queue
- **THEN** the worker SHALL NOT receive the message
- **AND** the message SHALL accumulate on the `topic` queue indefinitely


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
### Requirement: Existing tests for queue behaviour SHALL pass without regression

All existing tests under `backend/tests/` that exercise Celery task dispatch, throttling, and worker lifecycle SHALL continue to pass after the routing and priority configuration is added. The change SHALL NOT break the `transcribe_episode` task's interaction with the global concurrency semaphore, per-show lock, or graceful shutdown handler.

#### Scenario: Throttle semaphore continues to function

- **GIVEN** `MAX_CONCURRENT_TRANSCRIPTIONS=1` and one `transcribe_episode` task is currently active
- **WHEN** a second `transcribe_episode` task is enqueued (now to the `transcribe` queue with priority=9)
- **THEN** the second task SHALL still self-requeue via the existing `transcribe:global:active_count` check
- **AND** the per-show Redis lock SHALL still be honored

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