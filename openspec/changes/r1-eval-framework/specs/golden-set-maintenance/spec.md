## ADDED Requirements

### Requirement: Admin endpoint surfaces golden-set freshness per show

The backend SHALL expose `GET /admin/golden-set-status` (admin role required, 401 unauthenticated, 403 non-admin). The response body SHALL be a JSON list with one entry per show currently in the database; each entry SHALL contain:
- `show_id` (UUID)
- `show_title` (string)
- `show_slug` (string, derived consistently with the dataset filename convention)
- `dataset_exists` (bool — true iff `backend/eval/datasets/{show_slug}.json` is present in the deployed image)
- `item_count` (integer — items in the dataset, or 0 if not present)
- `last_updated` (ISO8601 string, the dataset's `created_at` field, or null if no dataset)
- `episodes_added_since` (integer — count of episode rows whose `created_at` is after the dataset's `last_updated`; if no dataset, equals total episode count)
- `needs_refresh` (bool — true iff `last_updated` is older than 30 days AND `episodes_added_since >= 10`)

#### Scenario: Show with fresh dataset reports needs_refresh=false

- **GIVEN** show "這又沒有很屌" has dataset created 5 days ago and 3 new episodes since
- **WHEN** an admin calls `GET /admin/golden-set-status`
- **THEN** the entry's `needs_refresh` SHALL be `false`

#### Scenario: Show with stale dataset and many new episodes reports needs_refresh=true

- **GIVEN** a show whose dataset is 35 days old with 15 new episodes since
- **WHEN** the endpoint is called
- **THEN** that entry's `needs_refresh` SHALL be `true`

#### Scenario: Show with no dataset reports null last_updated and needs_refresh=true

- **GIVEN** a show that has no `backend/eval/datasets/{slug}.json` file
- **WHEN** the endpoint is called
- **THEN** the entry SHALL have `dataset_exists: false`, `item_count: 0`, `last_updated: null`, `needs_refresh: true`

### Requirement: Monthly Celery beat task emails admin when datasets need refresh

A Celery beat schedule SHALL trigger a `golden_set_reminder` task on the 1st of each month at 03:00 UTC. The task SHALL:
1. Iterate over each show in the database
2. Compute the same `needs_refresh` flag as the admin endpoint
3. If at least one show has `needs_refresh: true`, send a single ZSend email to the configured admin recipient summarizing which shows need refresh and how many new episodes have been added since
4. If all shows are fresh OR no admin email is configured OR ZSend is not provisioned, log a single info-level message and exit cleanly without sending email

The task SHALL be idempotent within a calendar day: re-running on the same day SHALL not produce duplicate email notifications (the dispatch SHALL update a `last_reminder_sent_at` marker — implementation MAY use Redis key, app_settings row, or equivalent durable store).

#### Scenario: Two shows need refresh, one email sent

- **GIVEN** show A and show B both have `needs_refresh: true` while show C is fresh
- **WHEN** the monthly task runs
- **THEN** exactly one email SHALL be sent to admin
- **AND** the email body SHALL list show A and show B with their respective `episodes_added_since` counts
- **AND** show C SHALL NOT appear in the email

#### Scenario: All shows fresh — no email

- **GIVEN** every show has `needs_refresh: false`
- **WHEN** the task runs
- **THEN** no email SHALL be sent
- **AND** an info log line SHALL be emitted indicating zero shows needed refresh

#### Scenario: Same-day re-run does not duplicate emails

- **GIVEN** the task already ran today and sent an email
- **WHEN** the task is re-invoked the same day (manual trigger)
- **THEN** no second email SHALL be sent
- **AND** an info log line SHALL note the dedupe

#### Scenario: ZSend not provisioned — log and exit clean

- **GIVEN** `ZSEND_API_KEY` env is unset
- **WHEN** the task runs and at least one show needs refresh
- **THEN** no email SHALL be attempted
- **AND** a warning log line SHALL note the missing env var
- **AND** the task SHALL complete with success status (not raise)
