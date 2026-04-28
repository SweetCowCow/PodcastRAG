# transcription-schedule Specification

## Purpose

TBD - created by archiving change 'transcription-schedule-api'. Update Purpose after archive.

## Requirements

### Requirement: Show schedule settings persisted per show

The backend SHALL maintain a `show_schedules` table with at most one row per show. Each row SHALL store `enabled` (boolean), `frequency` (one of `daily`, `weekly`, `manual`), `run_time` (string in HH:MM UTC format), `whisper_model` (string), `max_episodes_per_run` (integer, ≥ 1, REQUIRED — replaces the previous `max_episodes` column whose `0 = unlimited` semantic is removed), `last_refresh_at` (nullable timestamp UTC), `last_refresh_status` (enum: `success`, `failed`, `never`, default `never`), and `last_refresh_message` (nullable string, max 500 chars). Rows SHALL be deleted automatically when the parent show is deleted (CASCADE).

When `frequency = manual`, the cron tick SHALL skip this show (manual is opt-out from auto-execution; the schedule row still stores the model and per-trigger episode cap for use by the manual "transcribe latest" UI button).

#### Scenario: Create schedule for a show

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` with `enabled=true, frequency=daily, run_time=06:00, whisper_model=whisper-1, max_episodes_per_run=5` and no existing schedule row for the show
- **THEN** the backend SHALL insert a new row in `show_schedules` with those fields, `last_refresh_status=never`, and return HTTP 200 with the created schedule

#### Scenario: Update existing schedule

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` and a schedule row for the show already exists
- **THEN** the backend SHALL update all provided fields on the existing row, set `updated_at` to current UTC, and return HTTP 200 with the updated schedule

#### Scenario: Get schedule for a show

- **WHEN** a client calls `GET /shows/{show_id}/schedule` and a schedule row exists
- **THEN** the backend SHALL return HTTP 200 with all schedule fields including `last_refresh_at`, `last_refresh_status`, `last_refresh_message`

#### Scenario: Get schedule for a show with no schedule

- **WHEN** a client calls `GET /shows/{show_id}/schedule` and no schedule row exists for the show
- **THEN** the backend SHALL return HTTP 404

#### Scenario: Delete schedule

- **WHEN** a client calls `DELETE /shows/{show_id}/schedule`
- **THEN** the backend SHALL delete the schedule row and return HTTP 204

#### Scenario: Schedule deleted when show is deleted

- **WHEN** a show is deleted via `DELETE /shows/{show_id}`
- **THEN** the associated schedule row SHALL be deleted automatically via CASCADE

#### Scenario: max_episodes_per_run is required

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` without `max_episodes_per_run` (or with value < 1)
- **THEN** the backend SHALL return HTTP 422 validation error

#### Scenario: Manual frequency disables cron

- **GIVEN** a schedule with `enabled=true, frequency=manual, run_time=06:00`
- **WHEN** the cron tick runs at 06:00
- **THEN** the cron tick SHALL NOT refresh or enqueue this show


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
### Requirement: Admin schedules list endpoint

The backend SHALL expose `GET /admin/schedules` that returns a list of all shows with their schedule settings and transcription status summary. Each item SHALL include `show_id`, `show_title`, `rss_url`, `schedule` (the schedule fields or null if no schedule exists), `pending_count` (number of episodes with no completed transcript), and `last_transcribed_at` (the most recent `updated_at` among all completed transcripts for that show, or null).

#### Scenario: List returns all shows

- **WHEN** a client calls `GET /admin/schedules` and there are 3 shows (2 with schedules, 1 without)
- **THEN** the response SHALL contain all 3 shows; shows without a schedule SHALL have `schedule: null`

#### Scenario: Pending count is accurate

- **WHEN** a show has 10 episodes of which 3 have `transcript.status = "completed"` and 1 has `status = "processing"`
- **THEN** that show's `pending_count` in the response SHALL equal 7 (episodes with no completed transcript)

#### Scenario: Last transcribed at is most recent completed timestamp

- **WHEN** a show has two completed transcripts with `updated_at` of `2026-04-20T10:00Z` and `2026-04-22T08:00Z`
- **THEN** `last_transcribed_at` SHALL equal `2026-04-22T08:00Z`


<!-- @trace
source: transcription-schedule-api
updated: 2026-04-24
code:
  - PodcastRAG.html
  - config.js
  - backend/app/schemas/episode.py
  - backend/docker-compose.yml
  - backend/app/schemas/show.py
  - backend/Dockerfile
  - backend/app/api/shows.py
  - backend/app/api/schedules.py
  - entrypoint.sh
  - backend/app/api/query.py
  - backend/app/services/rag.py
  - index.html
  - backend/app/models/__init__.py
  - src/Shared.jsx
  - prod-select.png
  - backend/app/schemas/schedule.py
  - backend/app/main.py
  - backend/app/models/show_schedule.py
  - .mcp.json
  - src/PodcastSelect.jsx
  - backend/alembic/versions/d2e3f4a5b6c7_add_show_schedules.py
  - zbpack.frontend.json
  - backend/app/api/episodes.py
  - src/App.jsx
  - Dockerfile
  - src/AdminPage.jsx
  - CLAUDE.md
  - src/QueryPage.jsx
  - src/TranscriptPage.jsx
-->

---
### Requirement: ScheduleTab frontend fetches real data

The frontend `ScheduleTab` component SHALL fetch `GET /admin/schedules` on mount and render the returned list. The loading state SHALL show a spinner while the request is in flight. On error, an error message SHALL be displayed. The legacy in-card enable/disable toggle SHALL NOT be rendered on cards. Editing a show's `enabled` field SHALL occur exclusively inside the "編輯排程" / "Edit Schedule" modal as a labelled "自動轉錄" / "Auto Transcribe" form field, and saving the modal SHALL call `PUT /shows/{show_id}/schedule` with all edited fields including `enabled`. The "Auto Transcribe" field SHALL display a helper text indicating that the setting will take effect once cron functionality is implemented (currently no runtime behaviour). The legacy "Sync All" page-level button SHALL NOT be rendered; batch operations SHALL instead be driven by the selection-based batch action bar (see admin-show-management-ui).

#### Scenario: Tab loads real schedule list on mount

- **WHEN** `ScheduleTab` mounts and `GET /admin/schedules` returns a list of shows
- **THEN** the tab SHALL render one card per show using API-returned fields; hardcoded mock data SHALL NOT be rendered

#### Scenario: Auto Transcribe field appears in Edit Schedule modal

- **WHEN** the user opens the "編輯排程" modal for a show
- **THEN** the modal SHALL render an "自動轉錄" form field bound to the schedule's `enabled` value
- **AND** the field SHALL display helper text noting the setting awaits the cron feature

#### Scenario: Saving the Edit Schedule modal persists enabled

- **WHEN** the user toggles the "自動轉錄" field in the modal and clicks the modal's confirm button
- **THEN** the frontend SHALL call `PUT /shows/{show_id}/schedule` with the updated `enabled` value
- **AND** on success the card SHALL be refreshed via `GET /admin/schedules`

#### Scenario: Legacy in-card toggle is removed

- **WHEN** any show card is rendered
- **THEN** the card SHALL NOT render the previous enable/disable toggle widget on the card body

#### Scenario: Legacy Sync All button is removed

- **WHEN** the `ScheduleTab` page header is rendered
- **THEN** the page SHALL NOT render the legacy "Sync All" / "同步所有" button
- **AND** batch operations SHALL be reachable only through the selection-based batch action bar

<!-- @trace
source: redesign-schedule-tab-actions
updated: 2026-04-25
code:
  - index.html
  - src/Shared.jsx
  - src/AdminPage.jsx
  - docs/case-studies/sync-naming-redesign.md
-->

---
### Requirement: Cron tick triggers refresh and enqueue per schedule

The backend SHALL run a Celery Beat-driven `cron_tick` task once per minute. On each tick, the task SHALL select all rows from `show_schedules` where `enabled = true` AND the current UTC time matches the schedule's next due moment derived from `frequency` and `run_time`. For each matched show, the task SHALL execute the following sequence atomically per show:

1. Refresh the show's episode list by re-fetching its RSS feed (same code path as the manual `POST /shows/{show_id}/refresh-episodes` endpoint)
2. On refresh success: update `show_schedules.last_refresh_at = now`, `last_refresh_status = success`, `last_refresh_message = "+N 集"` where N is the number of newly inserted episodes
3. On refresh failure: update `last_refresh_at = now`, `last_refresh_status = failed`, `last_refresh_message = <error summary, max 500 chars>`, and SKIP the enqueue step
4. After successful refresh, select up to `max_episodes_per_run` episodes for that show that have no existing `transcription_queue` row (or whose existing row has `status = completed` and the episode is newer than the last completed one), ordered by episode publish date descending (newest first)
5. Enqueue each selected episode by inserting/updating its row in `transcription_queue` per the `transcription-queue` capability rules

The cron tick SHALL handle each show independently — a failure for one show SHALL NOT prevent processing of other shows in the same tick.

#### Scenario: Daily schedule fires at run_time

- **GIVEN** a show with `enabled=true`, `frequency=daily`, `run_time=06:00`
- **WHEN** the cron tick runs at 06:00 UTC
- **THEN** the backend SHALL refresh that show's episodes and enqueue up to `max_episodes_per_run` of them

#### Scenario: Refresh failure is recorded and enqueue is skipped

- **WHEN** the cron tick runs for show S and the RSS fetch raises a network error
- **THEN** `show_schedules.last_refresh_status` SHALL be `failed`, `last_refresh_message` SHALL contain the truncated error
- **AND** no new rows SHALL be inserted into `transcription_queue` for show S in this tick

#### Scenario: One show's failure does not stop other shows

- **GIVEN** three shows A, B, C all due at the same tick
- **AND** show B's RSS fetch fails
- **WHEN** the cron tick runs
- **THEN** shows A and C SHALL still be refreshed and enqueued normally

#### Scenario: Disabled schedules are skipped

- **GIVEN** a show with `enabled=false`
- **WHEN** the cron tick runs
- **THEN** that show SHALL NOT be refreshed and SHALL NOT have anything enqueued, regardless of `frequency` / `run_time`

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