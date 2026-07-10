## MODIFIED Requirements

### Requirement: Permanent errors short-circuit Celery retry

When a Celery task raises an exception that the error classifier returns as `permanent`, the task SHALL NOT use Celery's `autoretry_for` retry path. Instead the task's exception handler SHALL:

1. Call `error_classifier.classify(exc)` first.
2. If permanent → FIRST finalize domain state (mark the transcript row `failed` and mark the transcription queue row `failed` via the queue-finish helper), THEN write a `task_failure_log` row with `failure_type='permanent'`, then re-raise or return WITHOUT calling `self.retry(...)`.
3. If transient or unknown → fall through to existing `autoretry_for` behaviour (Celery handles retry).

Failure-log recording SHALL be fail-open with respect to state finalization: when writing the `task_failure_log` row raises any exception, the handler SHALL log the recording error and complete normally — domain state finalization performed in step 2 SHALL NOT be undone or skipped because recording failed.

Handlers that run inside module-level coroutine functions (no bound Celery task context, e.g. the `_run` coroutine of `transcribe_episode`) SHALL NOT reference `self`; they SHALL pass `retry_count=0`. The bound `on_failure` hook remains the owner of real retry-count reporting.

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

#### Scenario: State finalization survives a failure-log recording error

- **GIVEN** a `transcribe_episode` permanent failure (e.g. audio chunking subprocess error) inside the module-level `_run` coroutine
- **WHEN** `record_task_failure` raises (for any reason, including programming errors such as an undefined-name reference)
- **THEN** the transcript row SHALL still end in `status='failed'`
- **AND** the transcription queue row SHALL still end in `status='failed'`
- **AND** no new dispatch of the same episode SHALL occur on subsequent dispatcher polls

#### Scenario: Module-level handler reports retry_count zero

- **WHEN** the permanent-error handler runs inside a module-level coroutine without a bound task context
- **THEN** the `task_failure_log` row SHALL carry `retry_count=0`
- **AND** the handler SHALL NOT raise `NameError`
