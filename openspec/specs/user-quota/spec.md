# user-quota Specification

## Purpose

TBD - created by archiving change 'authentication-system'. Update Purpose after archive.

## Requirements

### Requirement: Per-user query quota counters

Each row in the `users` table SHALL maintain three counters: `total_queries` (BIGINT, default 0, monotonic lifetime counter), `quota_remaining` (INT, default 100, decreased on each successful query, increased only by admin top-up), and `quota_initial` (INT, default 100, the value of `quota_remaining` at the moment of user creation, never modified afterwards).

#### Scenario: New user starts with default quota

- **WHEN** a new `users` row is created via Google OAuth callback
- **THEN** `total_queries` SHALL be 0, `quota_remaining` SHALL be 100, and `quota_initial` SHALL be 100

#### Scenario: total_queries never decreases

- **WHEN** the system updates a user's quota counters at any time
- **THEN** the new value of `total_queries` SHALL be greater than or equal to the previous value

#### Scenario: quota_initial is immutable after user creation

- **WHEN** any operation other than initial user insertion targets the `quota_initial` column
- **THEN** the value SHALL NOT change


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Query endpoint atomically decrements quota before invoking RAG

The backend `POST /shows/{show_id}/query` endpoint SHALL, after authenticating the user and before invoking embedding or LLM calls, execute a single SQL `UPDATE users SET quota_remaining = quota_remaining - 1, total_queries = total_queries + 1 WHERE id = :user_id AND quota_remaining > 0 RETURNING quota_remaining`. If the statement affects zero rows, the endpoint SHALL return HTTP 429 with error code `quota_exhausted` and SHALL NOT invoke any external LLM or embedding API.

#### Scenario: Successful query decrements quota by 1

- **WHEN** an authenticated user with `quota_remaining=10` sends a valid query request
- **THEN** the `users` row SHALL be updated to `quota_remaining=9` and `total_queries=total_queries+1` atomically before any LLM call
- **AND** the response SHALL include the resulting `quota_remaining=9` value (e.g., in a response field or header)

##### Example: quota counters after sequential queries

- **GIVEN** a user with `quota_remaining=3, total_queries=10, quota_initial=100`
- **WHEN** the user makes 3 successful queries
- **THEN** the user row reads `quota_remaining=0, total_queries=13, quota_initial=100`
- **AND WHEN** the user attempts a 4th query
- **THEN** the response is HTTP 429 `quota_exhausted` and the user row remains `quota_remaining=0, total_queries=13`

#### Scenario: Quota exhausted blocks query before LLM call

- **WHEN** an authenticated user with `quota_remaining=0` sends a query request
- **THEN** the response SHALL be HTTP 429 with body containing `error_code='quota_exhausted'`
- **AND** no embedding or LLM API SHALL be called for this request
- **AND** `total_queries` SHALL NOT be incremented

#### Scenario: Concurrent queries do not over-spend quota

- **WHEN** an authenticated user with `quota_remaining=1` sends two concurrent query requests that both reach the database before either commits
- **THEN** exactly one request SHALL succeed with `quota_remaining` becoming 0
- **AND** the other request SHALL receive HTTP 429 `quota_exhausted`

#### Scenario: Query failure after quota deduction does not refund

- **WHEN** the atomic quota decrement succeeds but the subsequent LLM call fails
- **THEN** `quota_remaining` SHALL remain decremented and SHALL NOT be refunded by the application
- **AND** `total_queries` SHALL remain incremented


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
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