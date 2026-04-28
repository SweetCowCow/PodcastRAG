## MODIFIED Requirements

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

### Requirement: Cancel pending row

The backend SHALL expose `POST /admin/queue/{queue_id}/cancel` that accepts an optional `force` query parameter (boolean, default false).

When `force=false` (or absent): the endpoint SHALL transition a row from `pending` to `cancelled` and SHALL return HTTP 409 Conflict for any other status (running, completed, failed, already-cancelled).

When `force=true`: the endpoint SHALL additionally accept rows with `status=running`. For a running row, the backend SHALL: (1) read `celery_task_id` from the row; (2) if non-null, call `celery_app.control.revoke(celery_task_id, terminate=True, signal='SIGTERM')`; (3) update the row to `status=cancelled`, `finished_at=now`, `error_message='Force cancelled by admin'`; (4) release the global throttle slot keyed by `celery_task_id`. If `celery_task_id` is null (worker had not yet written it back), the backend SHALL skip steps (2) and (4) and proceed with the DB update only.

For `status=completed`, `failed`, or already-`cancelled`, `force=true` SHALL still return HTTP 409 (force only escalates pending/running to cancelled — terminal states are immutable).

The response body for a successful force-cancel of a running row SHALL include `{"force_cancelled": true, "celery_task_id": <string or null>}`.

Cancelled rows SHALL remain in the table for history/audit but SHALL be skipped by the dispatcher.

#### Scenario: Cancel a pending row succeeds without force

- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel` for a row with `status=pending`
- **THEN** the backend SHALL update the row to `status=cancelled` and return HTTP 200

#### Scenario: Cancel a running row without force is rejected

- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel` (no `force` parameter or `force=false`) for a row with `status=running`
- **THEN** the backend SHALL return HTTP 409 with body explaining that running jobs require force-cancel

#### Scenario: Force-cancel a running row revokes Celery task

- **GIVEN** a queue row with `status=running` and `celery_task_id='abc-123'`
- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel?force=true`
- **THEN** the backend SHALL call `celery_app.control.revoke('abc-123', terminate=True, signal='SIGTERM')`
- **AND** SHALL update the row to `status=cancelled`, `finished_at=<now>`, `error_message='Force cancelled by admin'`
- **AND** SHALL release the global throttle slot for task `abc-123`
- **AND** SHALL return HTTP 200 with body `{"force_cancelled": true, "celery_task_id": "abc-123"}`

#### Scenario: Force-cancel a running row with null celery_task_id skips revoke

- **GIVEN** a queue row with `status=running` and `celery_task_id=null` (worker had not yet written it)
- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel?force=true`
- **THEN** the backend SHALL NOT call `revoke` and SHALL NOT release any throttle slot
- **AND** SHALL update the row to `status=cancelled`, `finished_at=<now>`, `error_message='Force cancelled by admin'`
- **AND** SHALL return HTTP 200 with body `{"force_cancelled": true, "celery_task_id": null}`

#### Scenario: Force-cancel a completed row is rejected

- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel?force=true` for a row with `status=completed`
- **THEN** the backend SHALL return HTTP 409 — terminal states cannot be force-cancelled

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
