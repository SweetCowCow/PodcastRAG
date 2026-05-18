## ADDED Requirements

### Requirement: Appeal submission endpoint accepts reason from disabled users

The backend SHALL expose `POST /auth/appeal` accepting a JSON body `{ "email": string, "reason": string }`. The endpoint SHALL NOT require authentication (disabled users have no session). The endpoint SHALL validate that `reason` is between 1 and 2000 characters trimmed. If valid AND the email corresponds to a user row with `status='disabled'`, the backend SHALL insert a new row in `account_appeals` and return HTTP 200 `{ "accepted": true, "appeal_id": "<uuid>" }`. If the email does not exist OR the user's `status != 'disabled'`, the backend SHALL return HTTP 200 `{ "accepted": true }` (no `appeal_id`) WITHOUT writing to `account_appeals`, to prevent account-existence enumeration. Invalid `reason` SHALL return HTTP 400 with error code `invalid_reason`.

#### Scenario: Disabled user submits appeal successfully

- **GIVEN** a user `foo@example.com` exists in `users` with `status='disabled'`
- **WHEN** an unauthenticated request `POST /auth/appeal` is sent with `{"email":"foo@example.com","reason":"我覺得停權是誤判"}`
- **THEN** the response SHALL be HTTP 200 with body containing `accepted=true` and a non-empty `appeal_id`
- **AND** a new row SHALL exist in `account_appeals` with that `email`, `reason`, `client_ip` populated, and `created_at` set to the current time

#### Scenario: Unknown email silently accepted without write

- **WHEN** `POST /auth/appeal` is sent with `{"email":"nobody@nowhere.com","reason":"test"}` where the email does not exist in `users`
- **THEN** the response SHALL be HTTP 200 with body `{"accepted":true}` (no `appeal_id` field)
- **AND** no row SHALL be inserted into `account_appeals`

#### Scenario: Active user email silently accepted without write

- **GIVEN** a user `active@example.com` exists in `users` with `status='active'`
- **WHEN** `POST /auth/appeal` is sent with that email
- **THEN** the response SHALL be HTTP 200 with body `{"accepted":true}` (no `appeal_id` field)
- **AND** no row SHALL be inserted into `account_appeals`

#### Scenario: Empty or oversize reason rejected

- **WHEN** `POST /auth/appeal` is sent with `reason=""` (empty after trim)
- **THEN** the response SHALL be HTTP 400 with error code `invalid_reason`
- **AND WHEN** `reason` exceeds 2000 characters
- **THEN** the response SHALL be HTTP 400 with error code `invalid_reason`

### Requirement: Appeal endpoint enforces per-IP daily rate limit

The backend SHALL allow at most 5 `POST /auth/appeal` submissions per client IP per UTC day. The 6th and subsequent submissions from the same IP within the same UTC day SHALL be rejected with HTTP 429 and error code `rate_limited`. The rate limit SHALL count all submissions regardless of whether they resulted in a written `account_appeals` row, so attackers cannot probe enumeration via the rate limit.

#### Scenario: Same IP submitting 6 times in one day is rate limited on the 6th

- **GIVEN** the same client IP has successfully submitted 5 appeals today
- **WHEN** the same IP sends a 6th `POST /auth/appeal` within the same UTC day
- **THEN** the response SHALL be HTTP 429 with error code `rate_limited`

### Requirement: account_appeals table schema

The database SHALL contain a table named `account_appeals` with columns `id` (UUID PRIMARY KEY), `email` (TEXT NOT NULL), `reason` (TEXT NOT NULL), `client_ip` (TEXT NULLABLE), `user_disabled_at_snapshot` (TIMESTAMPTZ NULLABLE), `created_at` (TIMESTAMPTZ NOT NULL DEFAULT now()), and `notified_at` (TIMESTAMPTZ NULLABLE). Indexes SHALL exist on `created_at` and `email`. The table SHALL be created via an Alembic migration.

#### Scenario: Migration creates the table with required columns

- **WHEN** the alembic migration is applied to a clean database
- **THEN** the `account_appeals` table SHALL exist with all columns listed in this requirement
- **AND** indexes on `created_at` and `email` SHALL be present

### Requirement: Daily appeal digest emails admins

The backend SHALL run a Celery beat task `appeal_digest` scheduled daily at 09:00 Asia/Taipei. The task SHALL query rows in `account_appeals` where `notified_at IS NULL` and `created_at >= now() - 25 hours`. If the result is non-empty, the task SHALL send a single email to all addresses listed in `ADMIN_EMAILS` containing one line per appeal (timestamp, email, truncated reason). After successful send, the task SHALL update `notified_at` to the current time for each row included. If the result is empty, the task SHALL skip without sending email.

#### Scenario: Digest with new appeals sends email and marks rows notified

- **GIVEN** two `account_appeals` rows exist with `notified_at IS NULL` and `created_at` within the last 25 hours
- **WHEN** the `appeal_digest` task runs
- **THEN** a single email SHALL be sent to every address in `ADMIN_EMAILS` containing both appeals
- **AND** both rows' `notified_at` SHALL be updated to the current time

#### Scenario: Digest with no new appeals does nothing

- **GIVEN** no `account_appeals` rows exist with `notified_at IS NULL`
- **WHEN** the `appeal_digest` task runs
- **THEN** no email SHALL be sent
