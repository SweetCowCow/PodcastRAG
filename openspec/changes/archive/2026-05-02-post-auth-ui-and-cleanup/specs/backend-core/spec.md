## ADDED Requirements

### Requirement: Admin stats endpoint returns aggregate counts

The backend SHALL expose `GET /admin/stats` (guarded by `require_admin`) returning aggregate counts of resources used by the Release Log page banner. The response body SHALL be a JSON object with exactly the fields `episodes_completed` (integer count of `transcripts.status='completed'`), `transcript_chunks` (integer count of rows in `transcript_chunks`), `shows` (integer count of rows in `shows`), and `users` (integer count of rows in `users`).

#### Scenario: Authenticated admin retrieves live stats

- **WHEN** an authenticated admin sends `GET /admin/stats`
- **THEN** the response SHALL be HTTP 200 with body `{"episodes_completed": <int>, "transcript_chunks": <int>, "shows": <int>, "users": <int>}`
- **AND** each field value SHALL match the corresponding live database count at request time

#### Scenario: Unauthenticated request rejected

- **WHEN** an unauthenticated request hits `GET /admin/stats`
- **THEN** the response SHALL be HTTP 401 with error code `not_authenticated`

#### Scenario: Member request rejected

- **WHEN** an authenticated user with `role='member'` sends `GET /admin/stats`
- **THEN** the response SHALL be HTTP 403 with error code `forbidden`
