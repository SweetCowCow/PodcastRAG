## MODIFIED Requirements

### Requirement: FastAPI application entrypoint

The backend SHALL provide a FastAPI application instance as the main entrypoint, configured with CORS middleware that allows credentialed requests only from origins explicitly listed in the `FRONTEND_ORIGIN` environment variable (comma-separated). The CORS middleware SHALL set `allow_credentials=True`, SHALL include `X-CSRF-Token` in `allow_headers`, and SHALL NOT use a wildcard `*` for `allow_origins`. The application SHALL register a global exception handler for `Exception` that returns the unified error response schema with CORS headers preserved. The application SHALL register, before any router, a CSRF-and-Origin-validation middleware that rejects state-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) targeting authenticated endpoints when either the `Origin` header is missing or not in the allowlist, or the `X-CSRF-Token` header is absent or does not match the request's `csrf_token` cookie.

#### Scenario: Application starts successfully

- **WHEN** the backend process starts with valid environment variables including `FRONTEND_ORIGIN`
- **THEN** the FastAPI application SHALL be accessible and return HTTP 200 on the health endpoint

#### Scenario: CORS allows configured frontend origin with credentials

- **WHEN** a credentialed request arrives from an origin listed in `FRONTEND_ORIGIN`
- **THEN** the response SHALL include `Access-Control-Allow-Origin` echoing that origin and `Access-Control-Allow-Credentials: true`

#### Scenario: CORS rejects wildcard preflight from foreign origin

- **WHEN** a preflight `OPTIONS` request arrives from an origin not listed in `FRONTEND_ORIGIN`
- **THEN** the response SHALL NOT include an `Access-Control-Allow-Origin` matching that foreign origin

#### Scenario: Global exception handler is registered at startup

- **WHEN** the FastAPI application is created
- **THEN** an exception handler bound to the base `Exception` class SHALL be registered on the application instance before any router is included

#### Scenario: CSRF-and-Origin middleware blocks unsafe state-changing request

- **WHEN** a `POST` request to an authenticated endpoint arrives without an `X-CSRF-Token` header
- **THEN** the request SHALL be rejected with HTTP 403 and error code `csrf_token_missing` before reaching the route handler

## ADDED Requirements

### Requirement: Authentication-related configuration via environment variables

The backend configuration object SHALL expose the following authentication-related environment variables: `GOOGLE_CLIENT_ID` (required), `GOOGLE_CLIENT_SECRET` (required), `GOOGLE_REDIRECT_URI` (required), `SESSION_SECRET` (required, used to sign ephemeral OAuth state cookie), `ADMIN_EMAILS` (optional, comma-separated, default empty), `FRONTEND_ORIGIN` (required, comma-separated for multiple values), and `SESSION_TTL_DAYS` (optional integer, default 14).

#### Scenario: Missing required auth env var prevents startup

- **WHEN** the backend process starts without `GOOGLE_CLIENT_ID` set in the environment
- **THEN** the application SHALL fail to start and SHALL log a descriptive error naming the missing variable

#### Scenario: Empty ADMIN_EMAILS is permitted

- **WHEN** the backend starts with `ADMIN_EMAILS` unset or empty
- **THEN** the application SHALL start successfully
- **AND** no email SHALL be auto-promoted to `admin` on first login
