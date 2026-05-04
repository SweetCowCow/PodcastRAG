# admin-user-management-ui Specification

## Purpose

TBD - created by archiving change 'authentication-system'. Update Purpose after archive.

## Requirements

### Requirement: Admin user management tab lists all users

The frontend admin section SHALL provide a "Users" tab (route `admin-users`) accessible only when the current user has `role='admin'`. The tab SHALL render a table listing all users from `GET /admin/users` with columns: Avatar, Name, Email, Role, Status, Provider, Created (date), Last login (date or em-dash if null), Total queries, Quota remaining, Notes (truncated), and Actions.

#### Scenario: Admin opens users tab

- **WHEN** an authenticated admin navigates to the Users tab
- **THEN** the table SHALL render one row per user returned by `GET /admin/users`
- **AND** every column listed above SHALL be present in the table header

#### Scenario: Non-admin cannot access users tab

- **WHEN** an authenticated user with `role='member'` navigates to the URL hash for the Users tab
- **THEN** the tab content SHALL NOT render and the user SHALL be redirected to a non-admin page
- **AND** the `GET /admin/users` request SHALL NOT be issued by the frontend


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Admin can edit role, status, and notes per user

Each row in the users table SHALL provide an "Edit" affordance that opens a modal allowing the admin to change `role` (admin / member), `status` (active / pending / disabled), and `notes` (free-text up to 500 characters). Saving SHALL call `PATCH /admin/users/{id}` with only the changed fields.

#### Scenario: Edit modal preloads current values

- **WHEN** the admin clicks Edit on a row whose user has `role='member'`, `status='active'`, `notes='trial user'`
- **THEN** the modal SHALL show the role selector preset to `member`, status preset to `active`, and the notes textarea containing `trial user`

#### Scenario: Save sends only changed fields

- **WHEN** the admin opens Edit and changes only `status` from `active` to `disabled`
- **THEN** the `PATCH /admin/users/{id}` request body SHALL be `{"status": "disabled"}` (no `role`, no `notes`)


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Admin can top up a user's remaining quota

Each row SHALL provide a "Top up" action that opens a small modal with a numeric input (default 100, accepting positive or negative integers). Submitting SHALL call `PATCH /admin/users/{id}/quota` with body `{"delta": <value>}` and SHALL update the displayed `Quota remaining` cell with the response value.

#### Scenario: Top-up modal accepts positive delta

- **WHEN** the admin enters `50` in the top-up input and submits, while the target user has `quota_remaining=20`
- **THEN** the request SHALL be `PATCH /admin/users/{id}/quota` with body `{"delta": 50}`
- **AND** upon a successful response containing `{"quota_remaining": 70}`, the table cell SHALL update to `70`

#### Scenario: Top-up modal accepts negative delta

- **WHEN** the admin enters `-10` and submits
- **THEN** the request body SHALL be `{"delta": -10}` (negative integer permitted)


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Admin can delete a user

Each row SHALL provide a Delete action that requires a confirmation dialog before calling `DELETE /admin/users/{id}`. After successful deletion, the row SHALL be removed from the table without a full page reload.

#### Scenario: Delete requires confirmation

- **WHEN** the admin clicks Delete on a row
- **THEN** a confirmation dialog SHALL appear displaying the target user's email
- **AND** the `DELETE /admin/users/{id}` request SHALL only be issued if the admin confirms

#### Scenario: Self-deletion is blocked at UI

- **WHEN** the admin clicks Delete on the row representing their own currently-logged-in user
- **THEN** the Delete action SHALL be disabled or a tooltip SHALL explain "Cannot delete your own account"


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Frontend displays current user info and remaining quota

The top navigation bar SHALL display the authenticated user's avatar, name, and remaining quota (e.g., "Remaining: 87"). When `quota_remaining` is 0, the indicator SHALL be styled in a danger color and the query input on `QueryPage` SHALL be disabled with a bilingual hint ("查詢額度已用完" / "Quota exhausted").

#### Scenario: Quota indicator updates after a query

- **WHEN** the query API responds with a payload that includes the new `quota_remaining`
- **THEN** the top-nav indicator SHALL re-render with the new value within the same render pass

#### Scenario: Logged-out top-nav shows Sign in button

- **WHEN** no authenticated session exists
- **THEN** the top-nav SHALL show a "Sign in with Google" button instead of avatar/name/quota
- **AND** clicking the button SHALL navigate the browser to `GET /auth/google/start` on the backend


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Bilingual labels in user management UI

All user-facing strings in the Users tab and current-user nav widget SHALL provide both Traditional Chinese and English variants, switched by the existing `lang` prop.

#### Scenario: Language toggle switches table headers

- **WHEN** the active language is changed from English to Traditional Chinese
- **THEN** the column headers SHALL update from "Avatar / Name / Email / Role / Status / Provider / Created / Last login / Total queries / Quota remaining / Notes / Actions" to the corresponding Traditional Chinese labels

<!-- @trace
source: authentication-system
updated: 2026-05-02
-->

<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Admin Quota Requests sub-tab lists pending and processed quota_requests

The admin Users page SHALL include a secondary tab labelled `Quota 申請` (`zh`) / `Quota requests` (`en`) accessible at route `admin-quota-requests`. The tab SHALL display a table with columns: requester email, reason (truncated to 100 chars with hover tooltip for full text), requested_at (relative time, e.g. `3 小時前`), current `quota_remaining` of the requester (live, fetched alongside the listing), status filter chips (`pending` / `approved` / `rejected`, default `pending`), and per-row action area. The tab SHALL fetch from `GET /admin/quota-requests?status=<filter>`. A red badge SHALL appear on the tab label whenever the count of pending requests is greater than zero.

#### Scenario: Pending tab loads pending requests sorted by requested_at ASC

- **GIVEN** 3 pending quota_requests with `requested_at` 1h, 5h, and 12h ago
- **WHEN** an admin opens the Quota 申請 tab with default `pending` filter
- **THEN** the table SHALL render 3 rows, oldest first (12h, 5h, 1h)

#### Scenario: Status filter chip switches the listing

- **WHEN** the admin clicks the `approved` filter chip
- **THEN** the table SHALL refetch with `?status=approved` and render the corresponding rows

#### Scenario: Pending count badge appears on tab label

- **GIVEN** 3 pending quota_requests exist
- **WHEN** an admin views the Users page
- **THEN** the `Quota 申請` tab label SHALL display a red `3` badge

#### Scenario: Empty state when no pending requests

- **WHEN** there are zero pending quota_requests and the admin opens the tab with the default filter
- **THEN** the table SHALL show an empty state message `目前沒有 pending 的 quota 申請` (`zh`) / `No pending quota requests` (`en`)
- **AND** no red badge SHALL appear on the tab label


<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->

---
### Requirement: Admin can approve a quota request inline with an amount

For each row in `pending` status, the action area SHALL contain an inline numeric input (default 30, min 1, max 1000) and a primary button `核准 +N` (`zh`) / `Approve +N` (`en`) that updates its label live as the input value changes. Clicking the button SHALL `POST /admin/quota-requests/{id}/approve` with `{"amount": <input>}`. On HTTP 200 the row SHALL be removed from the pending listing (or rendered as approved if the filter is `approved`). On HTTP 409 (`already_processed`) the page SHALL show a toast `此申請已被處理` (`zh`) / `This request has been processed` (`en`) and refetch.

#### Scenario: Approve adds quota and removes row from pending

- **GIVEN** the admin is viewing the `pending` filter with 3 rows
- **WHEN** the admin sets the amount to 50 on row R and clicks `核准 +50`
- **THEN** the API SHALL be called with `{"amount": 50}`
- **AND** on success, row R SHALL no longer appear in the table
- **AND** the requester's `quota_remaining` SHALL increase by 50 (verifiable via the user management tab)

#### Scenario: Already-processed approve shows toast and refetches

- **GIVEN** another admin already approved row R in another browser
- **WHEN** the current admin clicks `核准 +30` on row R
- **THEN** the API SHALL return HTTP 409
- **AND** the page SHALL show a toast and refetch the listing
- **AND** row R SHALL no longer appear in the pending listing


<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->

---
### Requirement: Admin can reject a quota request with a note

For each row in `pending` status, the action area SHALL also contain a secondary `拒絕` (`zh`) / `Reject` (`en`) button. Clicking it SHALL open a small confirmation dialog with a `<textarea>` labelled `拒絕原因（會寄給使用者—未來功能）` (`zh`) / `Rejection reason (will be sent to user — future)` (`en`) requiring at least 1 character, and a confirm button. On confirm, the page SHALL `POST /admin/quota-requests/{id}/reject` with `{"note": "<textarea>"}`. On HTTP 200 the row SHALL be removed from the pending listing.

#### Scenario: Reject removes row from pending

- **GIVEN** a pending row R
- **WHEN** the admin clicks `拒絕`, types `理由不充分`, and confirms
- **THEN** `POST /admin/quota-requests/{R}/reject` SHALL be called with `{"note": "理由不充分"}`
- **AND** on success, row R SHALL no longer appear in the pending listing
- **AND** the requester's `quota_remaining` SHALL be unchanged

#### Scenario: Reject without note is blocked client-side

- **WHEN** the admin clicks confirm with an empty textarea
- **THEN** the dialog SHALL show a validation error and SHALL NOT call the API

<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->