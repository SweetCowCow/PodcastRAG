## MODIFIED Requirements

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
