## ADDED Requirements

### Requirement: Celery application setup

The backend SHALL define a Celery application at `app.workers.celery_app` configured to use Redis as both broker and result backend, with `task_acks_late=True` and `worker_prefetch_multiplier=1`.

#### Scenario: Celery app boots

- **WHEN** the worker container starts with `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` both set to a reachable Redis instance
- **THEN** the Celery app SHALL import `app.workers.tasks` at startup and register all declared tasks without errors

#### Scenario: Missing broker rejected

- **WHEN** the worker starts without `CELERY_BROKER_URL`
- **THEN** the process SHALL exit with a configuration error before accepting any task

### Requirement: Redis service in docker-compose

The backend SHALL ship a `docker-compose.yml` definition that includes a `redis` service using an official Redis image, exposing the broker to the `backend` and `worker` services with a healthcheck.

#### Scenario: Compose stack starts

- **WHEN** `docker compose up` is run against the project compose file
- **THEN** `backend`, `worker`, `db`, and `redis` SHALL all report healthy within their configured healthchecks and the `worker` service SHALL wait for `redis` to be healthy before starting

### Requirement: Worker service in docker-compose

The backend SHALL ship a `worker` service in `docker-compose.yml` that reuses the backend image with command `celery -A app.workers.celery_app worker --loglevel=info` and shares the same database and object-storage environment as the API container.

#### Scenario: Worker picks up task

- **WHEN** the `worker` service is running and an API request enqueues `transcribe_episode(episode_id)`
- **THEN** the worker SHALL log that it received the task within 5 seconds of enqueue and SHALL execute it without shared-state errors

### Requirement: Task dispatch helper

The backend SHALL expose a helper `enqueue_transcription(episode_id)` that API endpoints call to send the transcription task to the queue, ensuring the task name and argument signature stay consistent.

#### Scenario: API uses helper

- **WHEN** `POST /episodes/{id}/transcribe` handles a new request
- **THEN** it SHALL call `enqueue_transcription(episode_id)` exactly once per accepted request rather than invoking Celery `send_task` directly
