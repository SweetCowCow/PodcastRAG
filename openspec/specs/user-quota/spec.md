# user-quota Specification

## Purpose

TBD - created by archiving change 'authentication-system'. Update Purpose after archive.

## Requirements

### Requirement: Per-user query quota counters

Each row in the `users` table SHALL maintain three counters: `total_queries` (BIGINT, default 0, monotonic lifetime counter), `quota_remaining` (INT, default value derived from `settings.default_user_quota`, decreased on each successful query, increased only by admin top-up or by approved quota_request), and `quota_initial` (INT, default same as `quota_remaining` at moment of user creation, never modified afterwards). The default quota value SHALL be configurable via env `DEFAULT_USER_QUOTA` (default 30); changing the env value SHALL only affect users created after the change — existing rows SHALL keep their original `quota_initial` and `quota_remaining` values.

#### Scenario: New user starts with default quota from setting

- **GIVEN** `DEFAULT_USER_QUOTA=30`
- **WHEN** a new `users` row is created via Google OAuth callback
- **THEN** `total_queries` SHALL be 0, `quota_remaining` SHALL be 30, and `quota_initial` SHALL be 30

#### Scenario: Default quota override propagates to new users only

- **GIVEN** an existing user U1 was created when `DEFAULT_USER_QUOTA=30` (so U1 has `quota_initial=30, quota_remaining=27` after some queries)
- **WHEN** the operator changes `DEFAULT_USER_QUOTA=50` and a new user U2 logs in for the first time
- **THEN** U2 SHALL have `quota_initial=50, quota_remaining=50`
- **AND** U1's `quota_initial` SHALL still be 30 and `quota_remaining` SHALL still be 27

#### Scenario: total_queries never decreases

- **WHEN** the system updates a user's quota counters at any time
- **THEN** the new value of `total_queries` SHALL be greater than or equal to the previous value

#### Scenario: quota_initial is immutable after user creation

- **WHEN** any operation other than initial user insertion targets the `quota_initial` column
- **THEN** the value SHALL NOT change


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
### Requirement: Query endpoint atomically decrements quota before invoking RAG

The backend `POST /shows/{show_id}/query` endpoint (which after this change handles only `mode="chat"` / LLM-answer requests) SHALL, after authenticating the user and before invoking embedding or LLM calls, execute a single SQL `UPDATE users SET quota_remaining = quota_remaining - 1, total_queries = total_queries + 1 WHERE id = :user_id AND quota_remaining > 0 RETURNING quota_remaining`. If the statement affects zero rows, the endpoint SHALL return HTTP 429 with error code `quota_exhausted` and SHALL NOT invoke any external LLM or embedding API. The public segment-search endpoint (`POST /shows/{show_id}/search`, see rag-query) SHALL NOT decrement `quota_remaining` regardless of whether the caller is authenticated.

#### Scenario: Successful chat query decrements quota by 1

- **WHEN** an authenticated user with `quota_remaining=10` sends a valid chat-mode request
- **THEN** the `users` row SHALL be updated to `quota_remaining=9` and `total_queries=total_queries+1` atomically before any LLM call
- **AND** the response SHALL include the resulting `quota_remaining=9` value

##### Example: quota counters after sequential queries

- **GIVEN** a user with `quota_remaining=3, total_queries=10, quota_initial=30`
- **WHEN** the user makes 3 successful chat queries
- **THEN** the user row reads `quota_remaining=0, total_queries=13, quota_initial=30`
- **AND WHEN** the user attempts a 4th chat query
- **THEN** the response is HTTP 429 `quota_exhausted` and the user row remains `quota_remaining=0, total_queries=13`

#### Scenario: Quota exhausted blocks chat query before LLM call

- **WHEN** an authenticated user with `quota_remaining=0` sends a chat query request
- **THEN** the response SHALL be HTTP 429 with body containing `error_code='quota_exhausted'`
- **AND** no embedding or LLM API SHALL be called for this request
- **AND** `total_queries` SHALL NOT be incremented

#### Scenario: Concurrent chat queries do not over-spend quota

- **WHEN** an authenticated user with `quota_remaining=1` sends two concurrent chat query requests that both reach the database before either commits
- **THEN** exactly one request SHALL succeed with `quota_remaining` becoming 0
- **AND** the other request SHALL receive HTTP 429 `quota_exhausted`

#### Scenario: Chat query failure after quota deduction does not refund

- **WHEN** the atomic quota decrement succeeds but the subsequent LLM call fails
- **THEN** `quota_remaining` SHALL remain decremented and SHALL NOT be refunded by the application
- **AND** `total_queries` SHALL remain incremented

#### Scenario: Public search endpoint does not decrement quota

- **WHEN** an authenticated user with `quota_remaining=10` calls the public segment-search endpoint
- **THEN** the response SHALL succeed and return ranked segments
- **AND** `quota_remaining` SHALL remain 10
- **AND** `total_queries` SHALL NOT be incremented


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
### Requirement: Admin can adjust quota_remaining via top-up endpoint

The backend SHALL expose `PATCH /admin/users/{user_id}/quota` accepting body `{"delta": <integer>}`. The endpoint SHALL be guarded by `require_admin`, SHALL clamp the resulting `quota_remaining` to the inclusive range `[0, 1_000_000]`, and SHALL return the updated value.

#### Scenario: Positive delta increases remaining quota

- **WHEN** an admin calls `PATCH /admin/users/{id}/quota` with body `{"delta": 50}` and the target user has `quota_remaining=20`
- **THEN** the user's `quota_remaining` SHALL become 70 and the response body SHALL contain `{"quota_remaining": 70}`

#### Scenario: Negative delta decreases remaining quota

- **WHEN** an admin calls the endpoint with `{"delta": -5}` and the target has `quota_remaining=10`
- **THEN** the user's `quota_remaining` SHALL become 5

#### Scenario: Delta clamped to non-negative floor

- **WHEN** an admin calls the endpoint with `{"delta": -999}` and the target has `quota_remaining=10`
- **THEN** the user's `quota_remaining` SHALL become 0 (not negative)

#### Scenario: total_queries is unaffected by admin adjustment

- **WHEN** an admin top-up modifies `quota_remaining`
- **THEN** the user's `total_queries` value SHALL NOT change

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