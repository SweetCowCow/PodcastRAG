## MODIFIED Requirements

### Requirement: Show schedule settings persisted per show

The backend SHALL maintain a `show_schedules` table with at most one row per show. Each row SHALL store `enabled` (boolean), `frequency` (one of `daily`, `weekly`, `manual`), `run_time` (string in HH:MM UTC format), `day_of_week` (integer in `[0, 6]`, NOT NULL, DEFAULT 0, where 0=Monday and 6=Sunday following Python `datetime.weekday()` convention), `whisper_model` (string), `max_episodes_per_run` (integer, ≥ 1, REQUIRED — replaces the previous `max_episodes` column whose `0 = unlimited` semantic is removed), `last_refresh_at` (nullable timestamp UTC), `last_refresh_status` (enum: `success`, `failed`, `never`, default `never`), and `last_refresh_message` (nullable string, max 500 chars). Rows SHALL be deleted automatically when the parent show is deleted (CASCADE).

The `day_of_week` column SHALL be consulted only when `frequency = weekly`. For `frequency = daily` and `frequency = manual`, the value of `day_of_week` SHALL be ignored by the cron tick (but still persisted as-is so users may switch frequencies without losing the prior selection).

When `frequency = manual`, the cron tick SHALL skip this show (manual is opt-out from auto-execution; the schedule row still stores the model and per-trigger episode cap for use by the manual "transcribe latest" UI button).

The Alembic migration that adds `day_of_week` SHALL backfill all existing rows to `0` (Monday), preserving the prior hard-coded weekly behavior for any rows already configured with `frequency = weekly`.

#### Scenario: Create schedule for a show

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` with `enabled=true, frequency=daily, run_time=06:00, whisper_model=whisper-1, max_episodes_per_run=5` and no existing schedule row for the show
- **THEN** the backend SHALL insert a new row in `show_schedules` with those fields, `day_of_week=0` (default), `last_refresh_status=never`, and return HTTP 200 with the created schedule

#### Scenario: Create weekly schedule with day_of_week

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` with `enabled=true, frequency=weekly, run_time=09:30, day_of_week=2, whisper_model=whisper-1, max_episodes_per_run=5`
- **THEN** the backend SHALL insert a new row with `day_of_week=2` and return HTTP 200

#### Scenario: Update existing schedule

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` and a schedule row for the show already exists
- **THEN** the backend SHALL update all provided fields on the existing row, set `updated_at` to current UTC, and return HTTP 200 with the updated schedule

#### Scenario: Get schedule for a show

- **WHEN** a client calls `GET /shows/{show_id}/schedule` and a schedule row exists
- **THEN** the backend SHALL return HTTP 200 with all schedule fields including `day_of_week`, `last_refresh_at`, `last_refresh_status`, `last_refresh_message`

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

#### Scenario: day_of_week out of range is rejected

- **WHEN** a client calls `PUT /shows/{show_id}/schedule` with `day_of_week=7` or `day_of_week=-1`
- **THEN** the backend SHALL return HTTP 422 validation error

#### Scenario: Manual frequency disables cron

- **GIVEN** a schedule with `enabled=true, frequency=manual, run_time=06:00`
- **WHEN** the cron tick runs at 06:00
- **THEN** the cron tick SHALL NOT refresh or enqueue this show

#### Scenario: Migration backfills existing rows to Monday

- **GIVEN** existing `show_schedules` rows with no `day_of_week` column prior to upgrade
- **WHEN** the Alembic migration runs
- **THEN** the `day_of_week` column SHALL be added with default 0 and all pre-existing rows SHALL have value 0 (Monday)

### Requirement: Cron tick triggers refresh and enqueue per schedule

The backend SHALL run a Celery Beat-driven `cron_tick` task once per minute. On each tick, the task SHALL select all rows from `show_schedules` where `enabled = true` AND the current UTC time matches the schedule's next due moment derived from `frequency`, `run_time`, and (for weekly) `day_of_week`. For each matched show, the task SHALL execute the following sequence atomically per show:

1. Refresh the show's episode list by re-fetching its RSS feed (same code path as the manual `POST /shows/{show_id}/refresh-episodes` endpoint)
2. On refresh success: update `show_schedules.last_refresh_at = now`, `last_refresh_status = success`, `last_refresh_message = "+N 集"` where N is the number of newly inserted episodes
3. On refresh failure: update `last_refresh_at = now`, `last_refresh_status = failed`, `last_refresh_message = <error summary, max 500 chars>`, and SKIP the enqueue step
4. After successful refresh, select up to `max_episodes_per_run` episodes for that show that have no existing `transcription_queue` row (or whose existing row has `status = completed` and the episode is newer than the last completed one), ordered by episode publish date descending (newest first)
5. Enqueue each selected episode by inserting/updating its row in `transcription_queue` per the `transcription-queue` capability rules

The cron tick SHALL handle each show independently — a failure for one show SHALL NOT prevent processing of other shows in the same tick.

The due-moment evaluation SHALL be:

- `frequency = daily`: due when the current UTC `HH:MM` equals `run_time`, every day
- `frequency = weekly`: due when the current UTC `HH:MM` equals `run_time` AND the current UTC weekday (per Python `datetime.weekday()`, 0=Monday..6=Sunday) equals `day_of_week`
- `frequency = manual`: never due (always skipped)

#### Scenario: Daily schedule fires at run_time

- **GIVEN** a show with `enabled=true`, `frequency=daily`, `run_time=06:00`
- **WHEN** the cron tick runs at 06:00 UTC
- **THEN** the backend SHALL refresh that show's episodes and enqueue up to `max_episodes_per_run` of them

#### Scenario: Weekly schedule fires only on configured day_of_week

- **GIVEN** a show with `enabled=true`, `frequency=weekly`, `run_time=09:30`, `day_of_week=2` (Wednesday)
- **WHEN** the cron tick runs at 09:30 UTC on a Wednesday
- **THEN** the backend SHALL refresh that show's episodes and enqueue up to `max_episodes_per_run` of them

##### Example: weekly due-evaluation across the week

| Current UTC weekday | Current UTC HH:MM | Schedule day_of_week | Schedule run_time | Due? |
| ------------------- | ----------------- | -------------------- | ----------------- | ---- |
| 2 (Wed)             | 09:30             | 2                    | 09:30             | yes  |
| 1 (Tue)             | 09:30             | 2                    | 09:30             | no   |
| 2 (Wed)             | 09:31             | 2                    | 09:30             | no   |
| 0 (Mon)             | 06:00             | 0                    | 06:00             | yes  |
| 6 (Sun)             | 23:00             | 6                    | 23:00             | yes  |

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
- **THEN** that show SHALL NOT be refreshed and SHALL NOT have anything enqueued, regardless of `frequency` / `run_time` / `day_of_week`
