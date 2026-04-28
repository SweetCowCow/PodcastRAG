## ADDED Requirements

### Requirement: DB-backed transcription queue table

The backend SHALL maintain a `transcription_queue` table where each row represents one episode's transcription job. Columns SHALL include: `id` (UUID, PK), `episode_id` (UUID, FK to episodes), `show_id` (UUID, FK to shows), `status` (enum: `pending`, `running`, `completed`, `failed`, `cancelled`), `position` (integer, monotonically assigned at enqueue, used for FIFO ordering of pending rows), `enqueued_at` (timestamp UTC), `started_at` (nullable timestamp UTC), `finished_at` (nullable timestamp UTC), `error_message` (nullable text), `ignored` (boolean, default false), `whisper_model` (string, snapshot of the model selected when enqueued).

`(episode_id)` SHALL be UNIQUE — at most one queue row per episode at any time. Re-enqueueing an already-`completed` or `failed` episode SHALL be modelled as a `status` transition (back to `pending`) on the existing row, NOT as a new row.

#### Scenario: Enqueue an episode for the first time

- **WHEN** the dispatcher receives a request to enqueue episode E for show S with model `whisper-1`
- **AND** no queue row exists for episode E
- **THEN** the backend SHALL insert a new row with `episode_id=E`, `show_id=S`, `status=pending`, `position` set to `MAX(position) + 1`, `enqueued_at=now`, `whisper_model=whisper-1`, `ignored=false`

#### Scenario: Re-enqueue a previously completed episode

- **WHEN** the dispatcher is asked to enqueue episode E and a queue row for E already exists with `status=completed`
- **THEN** the backend SHALL update the existing row: `status=pending`, `position=MAX(position) + 1`, `started_at=null`, `finished_at=null`, `error_message=null`

##### Example: re-enqueue keeps the same row id

- **GIVEN** queue row `id=R1, episode_id=E, status=completed, position=3`
- **AND** current `MAX(position) = 50`
- **WHEN** episode E is re-enqueued
- **THEN** row `R1` is updated to `status=pending, position=51` (NOT a new row R2)

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

### Requirement: Cancel pending row

The backend SHALL expose `POST /admin/queue/{queue_id}/cancel` that transitions a row from `pending` to `cancelled`. Cancelling a row with `status` other than `pending` SHALL return HTTP 409 Conflict (running, completed, failed, or already-cancelled rows cannot be cancelled via this endpoint). Cancelled rows SHALL remain in the table for history/audit but SHALL be skipped by the dispatcher.

#### Scenario: Cancel a pending row succeeds

- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel` for a row with `status=pending`
- **THEN** the backend SHALL update the row to `status=cancelled` and return HTTP 200

#### Scenario: Cancel a running row is rejected

- **WHEN** a client calls `POST /admin/queue/{queue_id}/cancel` for a row with `status=running`
- **THEN** the backend SHALL return HTTP 409 with body explaining that running jobs cannot be cancelled

### Requirement: Mark row as ignored

The backend SHALL expose `POST /admin/queue/{queue_id}/ignore` that sets `ignored = true` on the target row regardless of current status. Ignored rows SHALL be permanently skipped by both the dispatcher and the cron tick (cron tick MUST NOT re-enqueue an episode whose queue row has `ignored = true`, even if its status is `failed`).

The backend SHALL also expose `POST /admin/queue/{queue_id}/unignore` that sets `ignored = false`.

#### Scenario: Ignored failed row is not retried

- **WHEN** queue row R has `status=failed` AND `ignored=true`
- **AND** the cron tick runs and detects new episode that matches row R's episode_id
- **THEN** the cron tick SHALL NOT modify row R and SHALL NOT enqueue a new row for that episode

### Requirement: Cancel pending and running rows when show is deleted

When a show is deleted via `DELETE /shows/{show_id}`, the backend SHALL transition all `transcription_queue` rows for that show whose status is `pending` to `cancelled` BEFORE the show row is removed. Rows with `status = running` SHALL be transitioned to `cancelled` as well; the in-flight Celery task is not interrupted (Whisper API call already in progress) but its later attempt to write back to the queue row SHALL detect the `cancelled` status and abort writing transcript artifacts.

After the show is deleted, all queue rows for that show SHALL be removed via FK CASCADE on `episode_id`.

#### Scenario: Show deletion cancels pending queue rows first

- **WHEN** show S has 5 pending queue rows AND `DELETE /shows/{show_id}` is called
- **THEN** before the show is deleted, all 5 rows SHALL be updated to `status=cancelled`
- **AND** after the show is deleted, all 5 rows SHALL be removed by CASCADE

### Requirement: transcribe_episode task writes outcome back to queue row

The existing `transcribe_episode` Celery task SHALL look up the queue row matching its `episode_id` at start (set `started_at = now` if not already set) and at end (set `status = completed` and `finished_at = now` on success; set `status = failed`, `error_message = <truncated message>`, `finished_at = now` on permanent failure). On retryable transient failure, the row's `status` SHALL remain `running` (the Celery task itself retries internally).

If at the end of the task the queue row's `status` is `cancelled` (because the show was deleted mid-task), the task SHALL NOT write any transcript or chunk records and SHALL exit silently.

#### Scenario: Successful transcription updates queue row

- **WHEN** `transcribe_episode(E)` completes successfully
- **THEN** the queue row for E SHALL have `status=completed`, `finished_at` set to a timestamp ≥ `started_at`, and `error_message=null`

#### Scenario: Permanent failure records error message

- **WHEN** `transcribe_episode(E)` raises a permanent error (e.g. `RssParseError`, `StorageError`)
- **THEN** the queue row SHALL have `status=failed`, `error_message` populated with the truncated exception text (max 2000 chars), and `finished_at` set

#### Scenario: Mid-task cancellation aborts artifact writes

- **WHEN** `transcribe_episode(E)` reaches its write-results step
- **AND** the queue row's `status` has been set to `cancelled` by show deletion
- **THEN** the task SHALL NOT write transcript or chunk rows and SHALL log a cancellation notice

### Requirement: Global app_settings table for runtime configuration

The backend SHALL maintain an `app_settings` singleton table (one row enforced by application logic) with columns `max_concurrent_transcriptions` (integer, valid range 1–3 inclusive, default 1) and `monthly_cost_cap_usd` (numeric(10,2), nullable, default null, **reserved for future enforcement — not consumed by this change**). The dispatcher and `acquire_global_slot` SHALL read `max_concurrent_transcriptions` from this table on each enqueue/pop decision (or via a short-TTL cache, max 60 seconds).

#### Scenario: Concurrency change takes effect

- **WHEN** `max_concurrent_transcriptions` is updated from 1 to 3 in `app_settings`
- **AND** at most 60 seconds elapse
- **THEN** the dispatcher SHALL allow up to 3 rows in `status=running` simultaneously

#### Scenario: monthly_cost_cap_usd is not enforced in this change

- **WHEN** `monthly_cost_cap_usd` is set to any value (or null)
- **THEN** the dispatcher and cron tick SHALL behave identically — this field has no behavioural effect in this change
