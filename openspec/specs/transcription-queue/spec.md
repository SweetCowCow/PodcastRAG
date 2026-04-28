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

The dispatcher worker SHALL repeatedly select the lowest-`position` row from `transcription_queue` where `status = pending` AND `ignored = false`, atomically transition its `status` to `running` (with `started_at = now`), and invoke `transcribe_episode(episode_id)`. The dispatcher SHALL NOT use Celery broker FIFO for transcription job ordering; ordering is determined entirely by the `position` column.

The number of rows simultaneously in `status = running` SHALL NOT exceed `app_settings.max_concurrent_transcriptions`. When the limit is reached, the dispatcher SHALL wait until at least one row finishes (transitions out of `running`) before popping the next.

#### Scenario: FIFO order respected

- **WHEN** queue has pending rows with positions `[5, 8, 11]`
- **AND** all three are not ignored
- **THEN** the dispatcher SHALL process them in order `5, 8, 11`

#### Scenario: Concurrency limit respected

- **WHEN** `max_concurrent_transcriptions = 1` AND one row is in `status=running`
- **THEN** the dispatcher SHALL NOT transition any other pending row to `running` until the current running row reaches `completed`, `failed`, or `cancelled`


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


<!-- @trace
source: parallel-transcription-and-force-cancel
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
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