## ADDED Requirements

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
