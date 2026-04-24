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

The frontend `ScheduleTab` component SHALL fetch `GET /admin/schedules` on mount and render the returned list. The loading state SHALL show a spinner while the request is in flight. On error, an error message SHALL be displayed. Enabling or disabling a show's schedule SHALL call `PUT /shows/{show_id}/schedule` with the updated `enabled` field. The "Sync All" button SHALL call `POST /shows/{show_id}/transcribe-all` for each show that has an enabled schedule.

#### Scenario: Tab loads real schedule list on mount

- **WHEN** `ScheduleTab` mounts and `GET /admin/schedules` returns a list of shows
- **THEN** the tab SHALL render one card per show using API-returned fields; hardcoded mock data SHALL NOT be rendered

#### Scenario: Toggle enabled calls PUT

- **WHEN** the user toggles the enabled switch on a show card
- **THEN** the frontend SHALL call `PUT /shows/{show_id}/schedule` with `{ enabled: <new_value> }` and update the card state on success

#### Scenario: Sync All triggers transcribe-all per enabled show

- **WHEN** the user clicks "Sync All" and there are 2 enabled shows
- **THEN** the frontend SHALL call `POST /shows/{show_id}/transcribe-all` for each enabled show and display a success notification when all calls complete

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