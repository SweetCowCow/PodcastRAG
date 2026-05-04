## MODIFIED Requirements

### Requirement: Google OAuth callback exchanges code, upserts user, creates session

The backend SHALL expose `GET /auth/google/callback?code=&state=` which SHALL: (a) validate the `state` against the stored value, (b) exchange the `code` for tokens at Google's token endpoint using the stored `code_verifier`, (c) fetch the user's `email`, `name`, `picture`, and `sub` from Google's userinfo endpoint, (d) upsert a row in the `users` table keyed by `google_sub`, (e) create a session row, (f) set the session and CSRF cookies, and (g) return HTTP 302 redirecting to the configured frontend origin.

#### Scenario: First-time login creates a member user with default quota

- **WHEN** a user whose `email` is not in `ADMIN_EMAILS` and whose `google_sub` is not yet in the `users` table completes the Google OAuth flow
- **THEN** a new `users` row SHALL be inserted with `role='member'`, `status='active'`, `quota_remaining=settings.default_user_quota`, `quota_initial=settings.default_user_quota`, `total_queries=0`, and the `email`, `name`, `avatar_url`, and `google_sub` populated from Google's userinfo response

#### Scenario: First-time login from ADMIN_EMAILS allowlist creates an admin user

- **WHEN** a user whose `email` matches an entry in the comma-separated `ADMIN_EMAILS` environment variable completes the Google OAuth flow for the first time
- **THEN** the new `users` row SHALL be inserted with `role='admin'` and `status='active'`

##### Example: bootstrap admin via env

- **GIVEN** `ADMIN_EMAILS=foo@example.com,bar@example.com`
- **WHEN** `foo@example.com` completes Google login for the first time
- **THEN** the inserted `users` row has `role='admin'`
- **AND WHEN** `qux@example.com` completes Google login for the first time
- **THEN** the inserted `users` row has `role='member'`

#### Scenario: Returning login does not overwrite role or status

- **WHEN** a user whose `google_sub` already exists in the `users` table completes the Google OAuth flow again
- **THEN** the row's `role` and `status` columns SHALL NOT be modified by the callback
- **AND** the row's `last_login_at` SHALL be updated to the current timestamp

#### Scenario: State mismatch is rejected

- **WHEN** the `state` query parameter received from Google does not match the value stored in the ephemeral session
- **THEN** the response SHALL be HTTP 400 with error code `invalid_oauth_state` and no session SHALL be created

#### Scenario: Disabled user cannot complete login

- **WHEN** a user whose existing `users` row has `status='disabled'` completes the Google OAuth flow
- **THEN** no session SHALL be created and the response SHALL be HTTP 403 with error code `account_disabled`

#### Scenario: First-time login uses configured default quota when overridden

- **GIVEN** `DEFAULT_USER_QUOTA=50` is set in the environment
- **WHEN** a non-admin user completes Google login for the first time
- **THEN** the inserted `users` row SHALL have `quota_remaining=50` and `quota_initial=50`

### Requirement: Authentication dependencies gate protected endpoints

The backend SHALL provide three FastAPI dependencies. `require_authenticated_user` SHALL resolve the current user from the session cookie and reject unauthenticated requests with HTTP 401 `not_authenticated`. `require_admin` SHALL additionally require the resolved user's `role='admin'` and `status='active'`, rejecting otherwise with HTTP 403 `forbidden`. `optional_auth_with_ip_limit` SHALL resolve to a `User` if a valid session cookie is present; if no valid session, SHALL apply the per-IP daily rate limit (specified by the `ip-rate-limit` capability) and return `None` if under the limit, or raise HTTP 429 with `error_code='ip_rate_limited'` if at or beyond.

#### Scenario: Authenticated member calls admin endpoint

- **WHEN** an authenticated user with `role='member'` sends a request to an endpoint guarded by `require_admin`
- **THEN** the response SHALL be HTTP 403 with error code `forbidden`

#### Scenario: Unauthenticated request to admin endpoint

- **WHEN** an unauthenticated request arrives at an endpoint guarded by `require_admin`
- **THEN** the response SHALL be HTTP 401 with error code `not_authenticated`

#### Scenario: Authenticated admin passes both gates

- **WHEN** an authenticated user with `role='admin'` and `status='active'` sends a request to an endpoint guarded by `require_admin`
- **THEN** the request SHALL proceed to the route handler with the resolved `User` injected

#### Scenario: optional_auth_with_ip_limit returns user when authenticated

- **WHEN** an authenticated request arrives at an endpoint guarded by `optional_auth_with_ip_limit`
- **THEN** the dependency SHALL return the resolved `User`
- **AND** the IP rate limit counter SHALL NOT be touched

#### Scenario: optional_auth_with_ip_limit returns None for anonymous under limit

- **WHEN** an unauthenticated request arrives at an endpoint guarded by `optional_auth_with_ip_limit` and the IP counter is below the configured limit
- **THEN** the dependency SHALL return `None`
- **AND** the IP counter SHALL be incremented by 1

#### Scenario: optional_auth_with_ip_limit raises 429 when over limit

- **WHEN** an unauthenticated request arrives at an endpoint guarded by `optional_auth_with_ip_limit` and the IP counter is at or above the configured limit
- **THEN** the dependency SHALL raise `HTTPException(status_code=429)` with body containing `error_code='ip_rate_limited'`
- **AND** the route handler SHALL NOT be invoked
