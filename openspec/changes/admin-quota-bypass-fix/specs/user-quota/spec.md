## MODIFIED Requirements

### Requirement: Query endpoint atomically decrements quota before invoking RAG

The backend `POST /shows/{show_id}/query` endpoint (which after this change handles only `mode="chat"` / LLM-answer requests) SHALL, after authenticating the user and before invoking embedding or LLM calls, evaluate the user's `role`:

- **When `user.role != "admin"`**: the endpoint SHALL execute a single SQL `UPDATE users SET quota_remaining = quota_remaining - 1, total_queries = total_queries + 1 WHERE id = :user_id AND quota_remaining > 0 RETURNING quota_remaining`. If the statement affects zero rows, the endpoint SHALL return HTTP 429 with error code `quota_exhausted` and SHALL NOT invoke any external LLM or embedding API. The response SHALL include the resulting integer `quota_remaining` value.
- **When `user.role == "admin"`**: the endpoint SHALL NOT decrement `quota_remaining` and SHALL NOT return HTTP 429 `quota_exhausted` regardless of the current `quota_remaining` value (including `quota_remaining == 0`). The endpoint SHALL still execute `UPDATE users SET total_queries = total_queries + 1 WHERE id = :user_id` so admin usage remains observable. The response SHALL include `quota_remaining = -1` as the sentinel value indicating unlimited.

The public segment-search endpoint (`POST /shows/{show_id}/search`, see rag-query) SHALL NOT decrement `quota_remaining` regardless of whether the caller is authenticated or what their role is.

#### Scenario: Successful chat query by non-admin decrements quota by 1

- **WHEN** an authenticated user with `role="member"` and `quota_remaining=10` sends a valid chat-mode request
- **THEN** the `users` row SHALL be updated to `quota_remaining=9` and `total_queries=total_queries+1` atomically before any LLM call
- **AND** the response SHALL include the resulting `quota_remaining=9` value

##### Example: quota counters after sequential queries (non-admin)

- **GIVEN** a non-admin user with `quota_remaining=3, total_queries=10, quota_initial=30`
- **WHEN** the user makes 3 successful chat queries
- **THEN** the user row reads `quota_remaining=0, total_queries=13, quota_initial=30`
- **AND WHEN** the user attempts a 4th chat query
- **THEN** the response is HTTP 429 `quota_exhausted` and the user row remains `quota_remaining=0, total_queries=13`

#### Scenario: Quota exhausted blocks non-admin chat query before LLM call

- **WHEN** an authenticated user with `role="member"` and `quota_remaining=0` sends a chat query request
- **THEN** the response SHALL be HTTP 429 with body containing `error_code='quota_exhausted'`
- **AND** no embedding or LLM API SHALL be called for this request
- **AND** `total_queries` SHALL NOT be incremented

#### Scenario: Concurrent chat queries by non-admin do not over-spend quota

- **WHEN** an authenticated non-admin user with `quota_remaining=1` sends two concurrent chat query requests that both reach the database before either commits
- **THEN** exactly one request SHALL succeed with `quota_remaining` becoming 0
- **AND** the other request SHALL receive HTTP 429 `quota_exhausted`

#### Scenario: Chat query failure after quota deduction does not refund (non-admin)

- **GIVEN** a non-admin user with `quota_remaining=10` whose chat request triggers a downstream LLM failure
- **WHEN** the `_atomic_decrement_quota` UPDATE has already committed before the LLM call fails
- **THEN** `quota_remaining` SHALL remain at 9 (no refund)
- **AND** the response SHALL surface the LLM failure error to the caller

#### Scenario: Admin chat query does not decrement quota_remaining

- **GIVEN** an authenticated user with `role="admin"` and `quota_remaining=30, total_queries=N` in the database
- **WHEN** the user sends 200 sequential chat-mode requests
- **THEN** all 200 responses SHALL be non-429 (assuming downstream services succeed)
- **AND** the `users` row SHALL read `quota_remaining=30, total_queries=N+200` after the batch
- **AND** every response payload SHALL include `quota_remaining=-1` as the sentinel value

#### Scenario: Admin chat query bypasses 429 even when quota_remaining is 0

- **GIVEN** an authenticated user with `role="admin"` and `quota_remaining=0` (e.g. quota previously consumed before role was upgraded to admin)
- **WHEN** the user sends a chat-mode request
- **THEN** the response SHALL be HTTP 200 (not 429) and the embedding + LLM calls SHALL be invoked
- **AND** the response payload SHALL include `quota_remaining=-1`
- **AND** the DB `quota_remaining` SHALL remain 0 (admin path does NOT touch it)

#### Scenario: Admin total_queries counter still increments

- **GIVEN** an authenticated admin with `total_queries=100`
- **WHEN** the admin sends 5 chat requests
- **THEN** the `users` row SHALL read `total_queries=105` after the batch
- **AND** `quota_remaining` SHALL be unchanged
