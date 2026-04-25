# transcription-schedule Specification

## Purpose

TBD - created by archiving change 'transcription-schedule-api'. Update Purpose after archive.

## Requirements

### Requirement: Show schedule settings persisted per show

The backend SHALL maintain a `show_schedules` table with at most one row per show. Each row SHALL store `enabled` (boolean), `frequency` (one of `daily`, `weekly`, `manual`), `run_time` (string in HH:MM format), `whisper_model` (string), and `max_episodes` (integer, 0 = unlimited). Rows SHALL be deleted automatically when the parent show is deleted (CASCADE).

#### Scenario: Create schedule for a show

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` with valid schedule fields and no existing schedule row for the show
- **THEN** the backend SHALL insert a new row in `show_schedules` and return HTTP 200 with the created schedule

#### Scenario: Update existing schedule

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` and a schedule row for the show already exists
- **THEN** the backend SHALL update all provided fields on the existing row, set `updated_at` to current UTC, and return HTTP 200 with the updated schedule

#### Scenario: Get schedule for a show

- **WHEN** a client calls `GET /shows/{show_id}/schedule` and a schedule row exists
- **THEN** the backend SHALL return HTTP 200 with the schedule fields

#### Scenario: Get schedule for a show with no schedule

- **WHEN** a client calls `GET /shows/{show_id}/schedule` and no schedule row exists for the show
- **THEN** the backend SHALL return HTTP 404

#### Scenario: Delete schedule

- **WHEN** a client calls `DELETE /shows/{show_id}/schedule`
- **THEN** the backend SHALL delete the schedule row and return HTTP 204

#### Scenario: Schedule deleted when show is deleted

- **WHEN** a show is deleted via `DELETE /shows/{show_id}`
- **THEN** the associated schedule row SHALL be deleted automatically via CASCADE


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