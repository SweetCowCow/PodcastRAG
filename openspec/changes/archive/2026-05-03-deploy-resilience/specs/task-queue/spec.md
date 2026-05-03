## ADDED Requirements

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

## MODIFIED Requirements

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
