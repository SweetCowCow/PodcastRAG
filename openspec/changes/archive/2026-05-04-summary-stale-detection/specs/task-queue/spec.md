## ADDED Requirements

### Requirement: Cron tick scans for stale-running summary tasks

The `cron_tick` Celery task (already runs once per minute via Celery Beat) SHALL invoke a new helper, `_detect_stale_summary_running(session_factory)`, after the existing transcription-queue stale-running detection. The helper SHALL select rows from `episodes` where `ai_summary_status='running'` AND `ai_summary_started_at IS NOT NULL` AND `ai_summary_started_at < now() - settings.summary_stale_threshold_seconds * INTERVAL '1 second'`. For each selected row, the helper SHALL:

1. UPDATE the row to `ai_summary_status='pending'`, `ai_summary_started_at=NULL`, `ai_summary_error='recovered from stale running after <N>s'` (where `<N>` is the elapsed seconds at detection time).
2. Call `generate_episode_summary.delay(<episode_id>)`.

If step 2 raises (e.g. broker unreachable), the helper SHALL roll back the row's UPDATE for that row only and continue processing the remaining stale rows. The helper SHALL log the total count of rows recovered (or zero, silently). Exceptions raised by the helper itself (e.g. SELECT failure) SHALL be caught by `cron_tick` so the rest of the tick (schedule refresh, transcription stale detection, orphan revert) continues running.

#### Scenario: Stale summary row is reset and re-enqueued

- **GIVEN** a row in `episodes` with `ai_summary_status='running'` and `ai_summary_started_at = now() - 700s`
- **AND** `summary_stale_threshold_seconds = 600`
- **WHEN** `_run_tick()` invokes `_detect_stale_summary_running(Session)`
- **THEN** the row SHALL be UPDATEd to `ai_summary_status='pending'`, `ai_summary_started_at IS NULL`, `ai_summary_error LIKE 'recovered from stale running after %'`
- **AND** `generate_episode_summary.delay(<episode_id>)` SHALL be called exactly once

#### Scenario: Multiple stale rows are processed in one tick

- **GIVEN** 3 rows with `ai_summary_status='running'` and `ai_summary_started_at` 700s, 800s, 900s in the past
- **WHEN** `_run_tick()` invokes `_detect_stale_summary_running(Session)`
- **THEN** all 3 rows SHALL be reset to `pending` and 3 Celery tasks SHALL be enqueued
- **AND** the helper SHALL log `"cron_tick: stale summary recovered: 3 rows"`

#### Scenario: Helper exception does not break the rest of the tick

- **GIVEN** the SELECT inside `_detect_stale_summary_running` raises a database error
- **WHEN** `_run_tick()` runs
- **THEN** the exception SHALL be caught and logged with `exc_info=True`
- **AND** the subsequent schedule-refresh logic in `_run_tick()` SHALL still execute

#### Scenario: Per-row enqueue failure does not poison the batch

- **GIVEN** 2 stale rows; the first `generate_episode_summary.delay()` call raises (e.g. broker unreachable) and the second succeeds
- **WHEN** `_detect_stale_summary_running` runs
- **THEN** the first row SHALL be rolled back to `ai_summary_status='running'` (its UPDATE undone)
- **AND** the second row SHALL be reset to `pending` and its task enqueued
- **AND** the helper SHALL log a warning naming the failed row id
