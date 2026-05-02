## MODIFIED Requirements

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

## ADDED Requirements

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
