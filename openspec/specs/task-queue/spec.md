# task-queue Specification

## Purpose

TBD - created by archiving change 'transcription-pipeline'. Update Purpose after archive.

## Requirements

### Requirement: Celery application setup

The backend SHALL define a Celery application at `app.workers.celery_app` configured to use Redis as both broker and result backend, with `task_acks_late=True` and `worker_prefetch_multiplier=1`.

#### Scenario: Celery app boots

- **WHEN** the worker container starts with `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` both set to a reachable Redis instance
- **THEN** the Celery app SHALL import `app.workers.tasks` at startup and register all declared tasks without errors

#### Scenario: Missing broker rejected

- **WHEN** the worker starts without `CELERY_BROKER_URL`
- **THEN** the process SHALL exit with a configuration error before accepting any task


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/app/workers/celery_app.py
  - backend/app/workers/__init__.py
  - backend/app/workers/tasks.py
  - backend/app/core/config.py
  - backend/.env.example
  - backend/requirements.txt
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