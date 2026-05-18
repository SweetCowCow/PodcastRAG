## MODIFIED Requirements

### Requirement: Dispatcher pops jobs from DB queue in FIFO order

The dispatcher worker SHALL repeatedly select the lowest-`position` row from `transcription_queue` where `status = pending` AND `ignored = false` AND `dispatched_at IS NULL` using `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1` semantics, and invoke `transcribe_episode(episode_id)` by sending a Celery task to the broker. In the same DB transaction (before the `send_task` call), the dispatcher SHALL set `dispatched_at = NOW()` on the selected row and commit. This guarantees that a subsequent dispatcher tick cannot re-select the same row, eliminating the dispatcher self-race where two consecutive ticks both send a task for the same pending episode. The dispatcher SHALL NOT update the row's `status`, `started_at`, or `celery_task_id` fields when sending the task; those three fields SHALL be set by the worker task entry. The dispatcher SHALL use Celery broker FIFO + message priority for ordering at the broker layer; per-show ordering at the dispatch layer is determined entirely by the `position` column.

The number of rows simultaneously in `status = running` SHALL NOT exceed `app_settings.max_concurrent_transcriptions`. When the limit is reached, the dispatcher SHALL wait until at least one row finishes (transitions out of `running`) before sending the next task. The dispatcher SHALL count rows whose `status='running'` for this cap (i.e., it counts only rows that the worker has actually picked up, not rows the dispatcher has merely sent to the broker).

#### Scenario: FIFO order respected

- **WHEN** queue has pending rows with positions `[5, 8, 11]`
- **AND** all three are not ignored
- **THEN** the dispatcher SHALL send Celery tasks for them in order `5, 8, 11`

#### Scenario: Concurrency limit respected

- **WHEN** `max_concurrent_transcriptions = 1` AND one row is in `status=running`
- **THEN** the dispatcher SHALL NOT send another task to the broker until the current running row reaches `completed`, `failed`, or `cancelled`

#### Scenario: Dispatcher does not pre-mark row as running

- **GIVEN** a row R1 with `status='pending'`, `started_at=NULL`, `celery_task_id=NULL`, `dispatched_at=NULL`
- **WHEN** the dispatcher sends a Celery task for R1
- **THEN** R1 SHALL still have `status='pending'`, `started_at=NULL`, `celery_task_id=NULL` immediately after the dispatcher returns
- **AND** R1 SHALL have `dispatched_at` populated with the dispatcher's timestamp
- **AND** R1's status SHALL transition to `running` only when a worker picks the task up and runs its idempotent entry

#### Scenario: Dispatcher second tick does not re-select an already-dispatched pending row

- **GIVEN** a row R5 with `status='pending'`, `dispatched_at = NOW() - 30 seconds` (set by the previous dispatcher tick)
- **AND** the worker has not yet started processing R5 (broker queue depth > 0)
- **WHEN** the next dispatcher tick runs
- **THEN** the dispatcher SHALL NOT select R5 (filter `dispatched_at IS NULL` excludes it)
- **AND** the dispatcher SHALL NOT send a second Celery task for R5's episode

#### Scenario: Two concurrent dispatcher instances do not double-dispatch the same row

- **GIVEN** two dispatcher processes D1 and D2 running simultaneously (e.g., during a rolling deploy)
- **AND** a row R6 with `status='pending'`, `dispatched_at=NULL` is the next candidate
- **WHEN** D1 and D2 both attempt to claim R6 in the same instant
- **THEN** exactly one of them SHALL acquire the row lock via `SELECT ... FOR UPDATE SKIP LOCKED`
- **AND** the other SHALL skip R6 and select the next candidate row
- **AND** R6 SHALL receive exactly one Celery task

## ADDED Requirements

### Requirement: Worker task entry transitions queue row to running atomically

When the `transcribe_episode` Celery task starts execution on a worker, before any external I/O (Whisper call, transcript persist), the task SHALL execute an idempotent entry routine that:

1. Acquires a row-level lock on the matching `transcription_queue` row using `SELECT ... FOR UPDATE`.
2. Inspects the row's current `status` and `started_at`:
   - If `status='pending'` → update `status='running'`, `started_at=NOW()`, `celery_task_id=<this task id>`. Proceed with transcription.
   - If `status='running'` AND `started_at > NOW() - INTERVAL '5 minutes'` → log a warning containing the existing `celery_task_id` and the current task id, ack the message, and return without doing transcription work (treats the message as a duplicate).
   - If `status='running'` AND `started_at <= NOW() - INTERVAL '5 minutes'` → take ownership: update `started_at=NOW()`, `celery_task_id=<this task id>`, log a warning that an apparently stale running row was reclaimed. Proceed with transcription.
   - If `status` is `cancelled`, `completed`, `failed`, `ignored`, or any other terminal/excluded state → ack the message and return without doing transcription work.
3. Commits the lock release within the entry routine before any long-running work.

This entry routine SHALL run inside a single short DB transaction (target: under 50ms) and SHALL not call any external network service.

#### Scenario: Pending row is claimed and processed

- **GIVEN** a row R1 with `status='pending'`, `started_at=NULL`
- **WHEN** the worker picks up `transcribe_episode(R1.episode_id)` task with task id `T1`
- **THEN** the entry routine SHALL update R1 to `status='running'`, `started_at=NOW()`, `celery_task_id='T1'`
- **AND** the worker SHALL proceed to call the transcription provider

#### Scenario: Duplicate task within 5 minutes is acked and skipped

- **GIVEN** a row R2 with `status='running'`, `started_at = NOW() - 2 minutes`, `celery_task_id='T2-original'`
- **WHEN** the worker picks up a second task `T2-duplicate` for the same episode
- **THEN** the entry routine SHALL detect the live `running` state
- **AND** the worker SHALL ack `T2-duplicate` without calling the transcription provider
- **AND** R2's `started_at` and `celery_task_id` SHALL remain unchanged

#### Scenario: Stale running row beyond 5 minutes is reclaimed

- **GIVEN** a row R3 with `status='running'`, `started_at = NOW() - 12 minutes`, `celery_task_id='T3-ghost'` (the original task crashed without releasing)
- **WHEN** the worker picks up a fresh task `T3-new` for the same episode
- **THEN** the entry routine SHALL update R3 to `started_at=NOW()`, `celery_task_id='T3-new'`
- **AND** the worker SHALL proceed to call the transcription provider
- **AND** the routine SHALL log a warning naming both task ids

#### Scenario: Cancelled row is acked without work

- **GIVEN** a row R4 with `status='cancelled'`
- **WHEN** the worker picks up a previously-enqueued task `T4` for R4's episode
- **THEN** the entry routine SHALL ack `T4` without calling the transcription provider
- **AND** R4's `status` SHALL remain `cancelled`

---

### Requirement: Startup hook resets dispatcher-marked running rows to pending

When the backend service or worker service starts, before processing any new requests or tasks, the existing startup self-recovery routine SHALL also identify rows in either of two ambiguous states:

1. `status='running'` AND `started_at IS NULL` — the legacy state in which the previous dispatcher had not set `started_at` consistently or the row was orphaned by the migration cutover.
2. `status='pending'` AND `dispatched_at IS NOT NULL` AND `dispatched_at < NOW() - INTERVAL '5 minutes'` — the dispatcher set `dispatched_at` but the worker never picked up the task (dispatcher process crashed between commit and `send_task`, or broker dropped the message). The row is effectively stuck pending forever because the new dispatcher filter excludes `dispatched_at IS NOT NULL`.

Each such row SHALL be reset to `status='pending'`, `started_at=NULL`, `celery_task_id=NULL`, `dispatched_at=NULL`, `error_message=NULL` and SHALL have its global throttle slot released via `release_global_slot(<row_id_str>)`.

This requirement covers the deployment cutover from "dispatcher sets running" to "worker entry sets running" and SHALL remain in effect for any future state where a row's `status='running'` but its provenance is ambiguous (no `started_at`), or `status='pending'` but `dispatched_at` is stuck.

#### Scenario: Migration cutover row is reset on startup

- **GIVEN** a row R1 with `status='running'`, `started_at=NULL`, `celery_task_id=NULL` exists when the worker restarts
- **WHEN** the worker's startup self-recovery routine runs
- **THEN** R1 SHALL be updated to `status='pending'`, `error_message=NULL`
- **AND** `release_global_slot('<R1.id>')` SHALL be called

#### Scenario: Existing orphan-revert behaviour preserved

- **GIVEN** the existing orphan-revert requirement in this spec (queue rows where `celery_task_id` is not in `inspect().active() ∪ reserved()`)
- **WHEN** the new startup hook also runs
- **THEN** the existing orphan-revert SHALL run without conflict
- **AND** the same row SHALL not be reset twice in the same startup pass

#### Scenario: Stuck dispatched_at row is reset on startup

- **GIVEN** a row R7 with `status='pending'`, `dispatched_at = NOW() - 12 minutes`, `started_at=NULL` (dispatcher crashed before `send_task` completed, broker never received the task)
- **WHEN** the worker's startup self-recovery routine runs
- **THEN** R7 SHALL be updated to `status='pending'`, `dispatched_at=NULL`
- **AND** the next dispatcher tick SHALL be free to re-select R7

### Requirement: Worker entry and terminal transitions clear dispatched_at

The worker task entry routine and all terminal state transitions (completed / failed / cancelled) SHALL clear `dispatched_at` to NULL alongside their existing field updates. This ensures the dispatcher filter `dispatched_at IS NULL` correctly identifies rows that are eligible for a fresh dispatch when retried, restarted, or re-enqueued.

#### Scenario: Worker entry clears dispatched_at when transitioning to running

- **GIVEN** a row R8 with `status='pending'`, `dispatched_at='2026-05-18 09:00:00'`
- **WHEN** the worker picks up the task and the entry routine transitions R8 to `status='running'`
- **THEN** R8 SHALL also have `dispatched_at=NULL` after the transition

#### Scenario: Terminal completion clears dispatched_at

- **GIVEN** a row R9 with `status='running'`, `dispatched_at=NULL` (already cleared by entry)
- **WHEN** the task completes and transitions R9 to `status='completed'`
- **THEN** R9 SHALL retain `dispatched_at=NULL`
- **AND** no later code path SHALL reintroduce a non-NULL `dispatched_at` to R9 without going through the dispatcher

### Requirement: transcription_queue schema includes dispatched_at column

The `transcription_queue` table SHALL include a `dispatched_at` column of type `TIMESTAMPTZ NULLABLE` with default NULL. The column SHALL be added via an Alembic migration. An index on `(status, dispatched_at)` partial-filtered to `WHERE status='pending'` SHALL be created to make the dispatcher's primary query `WHERE status='pending' AND dispatched_at IS NULL` index-only and fast.

#### Scenario: Migration adds the column with correct type and default

- **WHEN** the alembic migration is applied to a clean database
- **THEN** `\d transcription_queue` SHALL show the `dispatched_at TIMESTAMPTZ NULLABLE` column with default NULL
- **AND** the partial index on `(status, dispatched_at) WHERE status='pending'` SHALL exist

#### Scenario: Existing rows in production receive NULL value during migration

- **GIVEN** the migration is applied to a production DB with existing `transcription_queue` rows
- **WHEN** the migration completes
- **THEN** every pre-existing row SHALL have `dispatched_at=NULL` (treated as eligible for dispatch on the next tick)
