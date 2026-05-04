## ADDED Requirements

### Requirement: Quota requests table tracks user-submitted quota top-up applications

The system SHALL maintain a `quota_requests` table where each row records one user's request for additional quota. The table SHALL contain: `id` (UUID PK), `user_id` (UUID FK → `users.id`, ON DELETE CASCADE), `reason` (TEXT NOT NULL), `status` (enum `quota_request_status_enum` with values `pending` / `approved` / `rejected`, NOT NULL DEFAULT `pending`), `granted_amount` (INTEGER, nullable — set only on approve), `rejection_note` (TEXT, nullable — set only on reject), `requested_at` (TIMESTAMPTZ NOT NULL DEFAULT now()), `processed_at` (TIMESTAMPTZ, nullable), `processed_by` (UUID FK → `users.id`, nullable), `last_digest_at` (TIMESTAMPTZ, nullable). Indexes SHALL exist on `(status, last_digest_at)` (for the digest cron query) and `(user_id, requested_at DESC)` (for "my requests" listings).

#### Scenario: Migration creates the table with empty rows

- **GIVEN** a database where `quota_requests` does not yet exist
- **WHEN** the migration runs
- **THEN** the table SHALL exist with the seven columns and three boolean states described above
- **AND** the indexes `(status, last_digest_at)` and `(user_id, requested_at DESC)` SHALL exist
- **AND** the row count SHALL be 0

#### Scenario: User deletion cascades to their quota requests

- **GIVEN** a user with two pending quota_requests rows
- **WHEN** the user row is deleted
- **THEN** both quota_requests rows SHALL be deleted

### Requirement: User can submit one pending quota request at a time

The backend SHALL expose `POST /quota-requests` guarded by `require_authenticated_user`. The body SHALL be `{"reason": "<string of at least 10 and at most 1000 characters>"}`. Before INSERTing the row, the endpoint SHALL check whether the user already has any quota_requests row with `status='pending'`; if so the endpoint SHALL return HTTP 409 with `error_code='quota_request_pending'` and SHALL NOT INSERT anything. On successful INSERT the response SHALL be HTTP 201 with the new row's id, requested_at, and status='pending'.

#### Scenario: First request succeeds

- **GIVEN** an authenticated user with no existing quota_requests
- **WHEN** the user POSTs `/quota-requests` with body `{"reason": "我用完了 quota 在做 Podcast 整理研究"}`
- **THEN** a new row SHALL be inserted with `status='pending'`, `reason` matching the body, `requested_at=now()`, all `*_at` and `*_amount` fields NULL
- **AND** the response SHALL be HTTP 201 with `{"id": ..., "status": "pending", "requested_at": ...}`

#### Scenario: Second pending request is rejected

- **GIVEN** an authenticated user who already has one quota_requests row with `status='pending'`
- **WHEN** the user POSTs `/quota-requests` with another body
- **THEN** the response SHALL be HTTP 409 with `error_code='quota_request_pending'`
- **AND** no new row SHALL be inserted

#### Scenario: Reason shorter than 10 characters is rejected

- **WHEN** the body has `reason` of length less than 10
- **THEN** the response SHALL be HTTP 422 with a validation error
- **AND** no row SHALL be inserted

#### Scenario: After previous request was processed, user can submit again

- **GIVEN** a user whose previous quota_requests row has `status='approved'` (or `rejected`)
- **WHEN** the user POSTs a new `/quota-requests`
- **THEN** the new row SHALL be inserted (the rule applies only to `pending` rows)

### Requirement: User can view their own quota request history

The backend SHALL expose `GET /quota-requests/me` guarded by `require_authenticated_user`. The response SHALL be a JSON array of the calling user's quota_requests rows ordered by `requested_at DESC`, including `id`, `status`, `reason`, `requested_at`, `processed_at`, `granted_amount`, `rejection_note`. The endpoint SHALL accept an optional `?status=` filter accepting `pending` / `approved` / `rejected`.

#### Scenario: Returns only own rows

- **GIVEN** user A has 2 quota_requests, user B has 3
- **WHEN** user A calls `GET /quota-requests/me`
- **THEN** the array SHALL contain exactly 2 elements, all belonging to user A

#### Scenario: Status filter works

- **GIVEN** user A has 1 pending and 2 approved quota_requests
- **WHEN** user A calls `GET /quota-requests/me?status=pending`
- **THEN** the array SHALL contain exactly 1 element with `status='pending'`

### Requirement: Admin can list and process quota requests

The backend SHALL expose three admin-only endpoints (guarded by `require_admin`):

1. `GET /admin/quota-requests?status=` — returns all rows ordered by `requested_at ASC` (oldest first), each augmented with the requester's email and current `quota_remaining`. Default filter is `status=pending`.
2. `POST /admin/quota-requests/{id}/approve` body `{"amount": <int>}` — atomically: SELECT row FOR UPDATE; if `status != 'pending'` return HTTP 409 `error_code='already_processed'`; UPDATE row to `status='approved', granted_amount=amount, processed_at=now(), processed_by=<admin user id>`; UPDATE the requester's `users.quota_remaining = quota_remaining + amount` (clamped to `[0, 1_000_000]` ceiling). The response SHALL include the updated user's new `quota_remaining`.
3. `POST /admin/quota-requests/{id}/reject` body `{"note": "<string>"}` — same atomicity as approve; UPDATE row to `status='rejected', rejection_note=note, processed_at=now(), processed_by=<admin user id>`. SHALL NOT modify the requester's `quota_remaining`.

#### Scenario: Approve adds quota and marks row processed

- **GIVEN** user A has `quota_remaining=5`, and a pending quota_request row R
- **WHEN** an admin POSTs `/admin/quota-requests/{R}/approve` with `{"amount": 50}`
- **THEN** row R SHALL have `status='approved'`, `granted_amount=50`, `processed_at` set, `processed_by` matching admin's id
- **AND** user A's `quota_remaining` SHALL become 55
- **AND** the response SHALL contain `{"quota_remaining": 55, "request_id": "<R>", "status": "approved"}`

#### Scenario: Reject does not modify quota

- **GIVEN** user A has `quota_remaining=5`, and a pending quota_request row R
- **WHEN** an admin POSTs `/admin/quota-requests/{R}/reject` with `{"note": "理由不充分"}`
- **THEN** row R SHALL have `status='rejected'`, `rejection_note='理由不充分'`, `processed_at` set
- **AND** user A's `quota_remaining` SHALL remain 5

#### Scenario: Already-processed row cannot be re-processed

- **GIVEN** a quota_request row R already in `status='approved'`
- **WHEN** an admin POSTs `/admin/quota-requests/{R}/approve` with any amount
- **THEN** the response SHALL be HTTP 409 with `error_code='already_processed'`
- **AND** no fields on R SHALL be modified
- **AND** no user quota SHALL be modified

#### Scenario: Approve clamps oversized amount

- **GIVEN** user A has `quota_remaining=999_950`
- **WHEN** an admin approves with `{"amount": 1000}`
- **THEN** user A's `quota_remaining` SHALL become `1_000_000` (ceiling), not `1_000_950`
- **AND** the admin SHALL receive HTTP 200 (clamping is silent — admin choice)

### Requirement: Beat scheduled task digests pending quota requests to admin email

The Celery worker SHALL register a task `app.workers.quota_digest.send_quota_digest` and Beat SHALL run it on cron `0 9,21 * * *` (UTC; equivalent to 17:00 + 05:00 next day Taipei time). The task SHALL:

1. Open a DB session and `SELECT * FROM quota_requests WHERE status='pending' AND (last_digest_at IS NULL OR last_digest_at < now() - INTERVAL '6 hours') ORDER BY requested_at ASC`.
2. If the result set is empty, log info `"quota_digest: no pending requests"` and return.
3. Otherwise, build a plain-text email with subject `"[PodcastRAG] {N} 筆 quota 申請待處理"` and body listing each row (user email, reason, requested_at ISO timestamp, age in hours), plus a footer link to `https://podcastrag.zeabur.app/admin/quota-requests`.
4. Parse `settings.zsend_admin_to_email` as comma-separated emails. For each recipient address, call ZSend's send endpoint with `from = settings.zsend_from_email`, `to = <recipient>`, the subject, and the plain-text body.
5. After all recipient sends complete (success or fail), `UPDATE quota_requests SET last_digest_at = now() WHERE id IN (<row ids returned in step 1>)`.

ZSend HTTP errors (non-2xx, timeout) SHALL trigger Celery `autoretry_for=(httpx.HTTPError, httpx.TimeoutException)` with `max_retries=2` and `retry_backoff=True`. After exhaustion the task SHALL log error and return; `last_digest_at` SHALL still be updated so the same rows do not bombard ZSend on the next 12-hour cron tick (the cooldown window protects against double-sending).

#### Scenario: Pending requests trigger one digest email per recipient

- **GIVEN** 3 pending quota_requests rows with `last_digest_at IS NULL`
- **AND** `ZSEND_ADMIN_TO_EMAIL='alice@example.com,bob@example.com'`
- **WHEN** `send_quota_digest` runs
- **THEN** ZSend SHALL be called exactly 2 times (once per recipient), each with the same subject `"[PodcastRAG] 3 筆 quota 申請待處理"`
- **AND** all 3 rows' `last_digest_at` SHALL be updated to approximately `now()`

#### Scenario: Already-digested rows within cooldown are skipped

- **GIVEN** 2 pending quota_requests rows: R1 with `last_digest_at = now() - 30 minutes`, R2 with `last_digest_at IS NULL`
- **WHEN** `send_quota_digest` runs
- **THEN** the email body SHALL include only R2's information (R1 is within the 6-hour cooldown)
- **AND** only R2's `last_digest_at` SHALL be updated

#### Scenario: Empty pending set sends no email

- **GIVEN** all quota_requests rows are in `approved` or `rejected` status
- **WHEN** `send_quota_digest` runs
- **THEN** no ZSend HTTP call SHALL be made
- **AND** an info log entry SHALL be written

#### Scenario: ZSend transient failure retries

- **GIVEN** ZSend returns 503 on first call attempt
- **WHEN** `send_quota_digest` runs
- **THEN** Celery autoretry SHALL trigger and the task SHALL retry up to 2 more times with backoff
- **AND** if any retry succeeds, the email SHALL be delivered exactly once
