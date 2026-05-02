# auth-system Specification

## Purpose

TBD - created by archiving change 'authentication-system'. Update Purpose after archive.

## Requirements

### Requirement: Google OAuth 2.0 login flow with PKCE

The backend SHALL implement Google Sign-In using OAuth 2.0 Authorization Code with PKCE. The flow SHALL be initiated by `GET /auth/google/start`, which SHALL generate a cryptographically random `state` value and `code_verifier`, store them in a server-side ephemeral session keyed by a temporary cookie with TTL of 5 minutes, and return an HTTP 302 redirect to Google's authorization endpoint with `client_id`, `redirect_uri`, `response_type=code`, `scope=openid email profile`, `state`, `code_challenge`, and `code_challenge_method=S256`.

#### Scenario: Start endpoint redirects to Google with PKCE parameters

- **WHEN** an unauthenticated user navigates to `GET /auth/google/start`
- **THEN** the response SHALL be HTTP 302 with a `Location` header pointing to `https://accounts.google.com/o/oauth2/v2/auth` and query parameters including `code_challenge`, `code_challenge_method=S256`, and a unique `state` value
- **AND** an ephemeral session cookie SHALL be set carrying a reference to the stored `state` and `code_verifier`


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Google OAuth callback exchanges code, upserts user, creates session

The backend SHALL expose `GET /auth/google/callback?code=&state=` which SHALL: (a) validate the `state` against the stored value, (b) exchange the `code` for tokens at Google's token endpoint using the stored `code_verifier`, (c) fetch the user's `email`, `name`, `picture`, and `sub` from Google's userinfo endpoint, (d) upsert a row in the `users` table keyed by `google_sub`, (e) create a session row, (f) set the session and CSRF cookies, and (g) return HTTP 302 redirecting to the configured frontend origin.

#### Scenario: First-time login creates a member user with default quota

- **WHEN** a user whose `email` is not in `ADMIN_EMAILS` and whose `google_sub` is not yet in the `users` table completes the Google OAuth flow
- **THEN** a new `users` row SHALL be inserted with `role='member'`, `status='active'`, `quota_remaining=100`, `quota_initial=100`, `total_queries=0`, and the `email`, `name`, `avatar_url`, and `google_sub` populated from Google's userinfo response

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


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Session cookie carries opaque server-side session

The backend SHALL store sessions in a `sessions` table and SHALL identify the session via an httpOnly cookie named `session_id` with attributes `Secure`, `SameSite=None`, `Path=/`, and `Max-Age=1209600` (14 days). The cookie value SHALL be a random 32-byte URL-safe token. The `sessions` row SHALL store `id` (UUID), `user_id` (FK to users), `session_token_hash` (SHA-256 of the cookie value), `csrf_token_hash`, `created_at`, `expires_at`, `last_seen_at`, `ip`, and `user_agent`.

#### Scenario: Cookie attributes are present

- **WHEN** the OAuth callback successfully creates a session
- **THEN** the `Set-Cookie` header for `session_id` SHALL include `HttpOnly`, `Secure`, `SameSite=None`, and `Max-Age=1209600`

#### Scenario: Server stores hashed token, not plaintext

- **WHEN** a session row is created
- **THEN** the `session_token_hash` column SHALL contain the SHA-256 hex digest of the cookie value
- **AND** the plaintext cookie value SHALL NOT be persisted anywhere on the server

#### Scenario: Sliding expiration on activity

- **WHEN** an authenticated request is processed and the session is still within `expires_at`
- **THEN** the `last_seen_at` column SHALL be updated to the current timestamp
- **AND** the `expires_at` column SHALL be extended to `now() + 14 days`

#### Scenario: Expired session is rejected

- **WHEN** a request arrives carrying a `session_id` cookie whose corresponding row has `expires_at < now()`
- **THEN** the request SHALL be treated as unauthenticated
- **AND** the expired row SHALL be deleted


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: CSRF token cookie protects state-changing requests

The backend SHALL set a non-httpOnly cookie named `csrf_token` alongside the session cookie, with attributes `Secure`, `SameSite=None`, `Path=/`. State-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) to any authenticated endpoint SHALL require an `X-CSRF-Token` header whose value matches the value of the `csrf_token` cookie of the same session, validated using constant-time comparison.

#### Scenario: Missing CSRF header is rejected on state-changing request

- **WHEN** an authenticated `POST` request arrives without an `X-CSRF-Token` header
- **THEN** the response SHALL be HTTP 403 with error code `csrf_token_missing`

#### Scenario: Mismatched CSRF token is rejected

- **WHEN** an authenticated `POST` request arrives with `X-CSRF-Token` header whose value does not equal the request's `csrf_token` cookie
- **THEN** the response SHALL be HTTP 403 with error code `csrf_token_invalid`

#### Scenario: GET requests bypass CSRF check

- **WHEN** an authenticated `GET` request arrives without an `X-CSRF-Token` header
- **THEN** the request SHALL be processed normally and the absence of the header SHALL NOT cause a CSRF error

##### Example: CSRF check matrix

| Method | X-CSRF-Token header | csrf_token cookie | Result |
|--------|---------------------|-------------------|--------|
| GET | absent | present | allow |
| POST | absent | present | 403 csrf_token_missing |
| POST | "abc" | "abc" | allow |
| POST | "abc" | "xyz" | 403 csrf_token_invalid |
| DELETE | "abc" | "abc" | allow |


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Origin header is validated on state-changing requests

The backend SHALL validate the `Origin` request header on `POST`, `PUT`, `PATCH`, and `DELETE` requests. The header SHALL be present and SHALL exactly match an entry in the configured frontend origin allowlist (`FRONTEND_ORIGIN` environment variable, comma-separated for multiple values).

#### Scenario: Missing Origin on state-changing request is rejected

- **WHEN** a `POST` request arrives without an `Origin` header and the request is targeting an authenticated endpoint
- **THEN** the response SHALL be HTTP 403 with error code `origin_missing`

#### Scenario: Foreign Origin is rejected

- **WHEN** a `POST` request arrives with `Origin: https://evil.example.com` and `https://evil.example.com` is not in the allowlist
- **THEN** the response SHALL be HTTP 403 with error code `origin_forbidden`


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Logout endpoint revokes session

The backend SHALL expose `POST /auth/logout` which SHALL delete the `sessions` row identified by the request's `session_id` cookie and SHALL return `Set-Cookie` headers that immediately expire both `session_id` and `csrf_token` cookies.

#### Scenario: Logout deletes session row

- **WHEN** an authenticated user calls `POST /auth/logout` with a valid session cookie and matching CSRF header
- **THEN** the `sessions` row identified by the cookie's hash SHALL be deleted
- **AND** the response SHALL contain `Set-Cookie: session_id=; Max-Age=0` and `Set-Cookie: csrf_token=; Max-Age=0`

#### Scenario: Logout is idempotent

- **WHEN** `POST /auth/logout` is called with a `session_id` cookie that does not match any existing session row
- **THEN** the response SHALL be HTTP 200 and SHALL still emit the cookie-clearing headers


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Current-user endpoint returns identity and quota

The backend SHALL expose `GET /me` which SHALL return the authenticated user's `id`, `email`, `name`, `avatar_url`, `role`, `status`, `total_queries`, `quota_remaining`, and `quota_initial`. The endpoint SHALL return HTTP 401 with error code `not_authenticated` when no valid session is present.

#### Scenario: Authenticated GET /me returns user payload

- **WHEN** an authenticated user calls `GET /me`
- **THEN** the response SHALL be HTTP 200 with a JSON body containing exactly the fields `id`, `email`, `name`, `avatar_url`, `role`, `status`, `total_queries`, `quota_remaining`, `quota_initial`

#### Scenario: Unauthenticated GET /me returns 401

- **WHEN** a request to `GET /me` carries no `session_id` cookie or an invalid/expired one
- **THEN** the response SHALL be HTTP 401 with body `{"detail": {"error_code": "not_authenticated", "provider": null, "detail": "Not authenticated"}}`


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Authentication dependencies gate protected endpoints

The backend SHALL provide two FastAPI dependencies: `require_authenticated_user` SHALL resolve the current user from the session cookie and reject unauthenticated requests with HTTP 401 `not_authenticated`; `require_admin` SHALL additionally require the resolved user's `role='admin'` and `status='active'`, rejecting otherwise with HTTP 403 `forbidden`.

#### Scenario: Authenticated member calls admin endpoint

- **WHEN** an authenticated user with `role='member'` sends a request to an endpoint guarded by `require_admin`
- **THEN** the response SHALL be HTTP 403 with error code `forbidden`

#### Scenario: Unauthenticated request to admin endpoint

- **WHEN** an unauthenticated request arrives at an endpoint guarded by `require_admin`
- **THEN** the response SHALL be HTTP 401 with error code `not_authenticated`

#### Scenario: Authenticated admin passes both gates

- **WHEN** an authenticated user with `role='admin'` and `status='active'` sends a request to an endpoint guarded by `require_admin`
- **THEN** the request SHALL proceed to the route handler with the resolved `User` injected

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