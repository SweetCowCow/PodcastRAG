# backend-core Specification

## Purpose

TBD - created by archiving change 'backend-api'. Update Purpose after archive.

## Requirements

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


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Health check endpoint

The backend SHALL expose a `GET /health` endpoint that returns the current health status of the service.

#### Scenario: Service is healthy

- **WHEN** `GET /health` is called and the database connection is reachable
- **THEN** the response SHALL be HTTP 200 with JSON body `{"status": "ok", "database": "connected"}`

#### Scenario: Database is unreachable

- **WHEN** `GET /health` is called and the database connection fails
- **THEN** the response SHALL be HTTP 503 with JSON body `{"status": "error", "database": "disconnected"}`


<!-- @trace
source: backend-api
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/alembic/env.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/database.py
  - backend/alembic/script.py.mako
  - backend/docker-compose.yml
  - backend/app/main.py
  - backend/alembic.ini
  - backend/app/models/transcript_segment.py
  - backend/.dockerignore
  - backend/app/models/episode.py
  - backend/alembic/README
  - backend/app/core/__init__.py
  - backend/app/__init__.py
  - backend/app/models/show.py
  - .spectra/spectra.db
  - backend/requirements.txt
  - backend/app/models/__init__.py
  - backend/app/api/__init__.py
  - backend/Dockerfile
  - backend/.env.example
  - backend/app/core/config.py
-->

---
### Requirement: Configuration management via environment variables

The backend SHALL read all configuration values from environment variables using pydantic-settings, with no hardcoded secrets or connection strings in source code. Authentication-related variables (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `SESSION_SECRET`) SHALL be defined as `Optional[str] = None` in the Settings model so that worker / dispatcher / beat entrypoints can import the settings module without these variables being set. The web service entrypoint (`app.main`) SHALL enforce these variables as required at lifespan startup (see "Web service requires Google OAuth and session env at startup").

#### Scenario: Valid configuration loaded

- **WHEN** all required environment variables are present in `.env` or the environment
- **THEN** the application SHALL start and all settings SHALL be accessible via the settings object

#### Scenario: Missing required environment variable

- **WHEN** a required environment variable (e.g., `DATABASE_URL`) is absent
- **THEN** the application SHALL fail to start and log a descriptive error indicating which variable is missing

#### Scenario: Authentication env optional for non-web entrypoints

- **WHEN** a worker, dispatcher, or beat process imports `app.core.config.settings` while `GOOGLE_CLIENT_ID` is unset
- **THEN** the Settings instance SHALL be constructed without raising
- **AND** `settings.google_client_id` SHALL be `None`


<!-- @trace
source: deploy-resilience
updated: 2026-05-03
code:
  - backend/app/main.py
  - backend/app/workers/cron_tick.py
  - backend/app/workers/throttle.py
  - backend/app/workers/celery_app.py
  - backend/app/workers/tasks.py
  - backend/app/workers/lifecycle.py
  - backend/app/api/queue.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/config.py
tests:
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_worker_lifecycle.py
  - backend/tests/test_web_service_env_validation.py
  - backend/tests/test_force_cancel_throttle.py
  - backend/tests/test_queue_cancel.py
-->

---
### Requirement: Async database session management

The backend SHALL provide an async SQLAlchemy session factory, injected via FastAPI dependency injection, that opens a session per request and closes it after the response.

#### Scenario: Session is available during request

- **WHEN** a route handler declares a `db: AsyncSession` dependency
- **THEN** an async database session SHALL be injected and committed on success

#### Scenario: Session is closed on exception

- **WHEN** a route handler raises an unhandled exception
- **THEN** the session SHALL be rolled back and closed without leaking the connection

<!-- @trace
source: backend-api
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/alembic/env.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/database.py
  - backend/alembic/script.py.mako
  - backend/docker-compose.yml
  - backend/app/main.py
  - backend/alembic.ini
  - backend/app/models/transcript_segment.py
  - backend/.dockerignore
  - backend/app/models/episode.py
  - backend/alembic/README
  - backend/app/core/__init__.py
  - backend/app/__init__.py
  - backend/app/models/show.py
  - .spectra/spectra.db
  - backend/requirements.txt
  - backend/app/models/__init__.py
  - backend/app/api/__init__.py
  - backend/Dockerfile
  - backend/.env.example
  - backend/app/core/config.py
-->

---
### Requirement: Unified error response schema

The backend SHALL define a single error response schema `ErrorResponse` containing the fields `error_code` (machine-readable snake_case string), `provider` (human-readable provider label, optional), and `detail` (English fallback message). All HTTP error responses returned by application endpoints SHALL serialize their body as `{"detail": <ErrorResponse dict>}` so that clients receive a consistent shape across 4xx and 5xx responses.

#### Scenario: Endpoint raises HTTPException with ErrorResponse detail

- **WHEN** an endpoint raises `HTTPException(status_code=429, detail=ErrorResponse(error_code="llm_quota_exceeded", provider="OpenAI", detail="...").model_dump())`
- **THEN** the response body SHALL be `{"detail": {"error_code": "llm_quota_exceeded", "provider": "OpenAI", "detail": "..."}}` with the corresponding status code

#### Scenario: ErrorResponse provider is omitted when not applicable

- **WHEN** an error has no associated external provider (e.g., validation, internal_error)
- **THEN** the `provider` field SHALL be `null` in the JSON response


<!-- @trace
source: friendly-external-api-errors
updated: 2026-05-01
code:
  - backend/app/main.py
  - backend/app/api/shows.py
  - src/i18n.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/errors.py
  - src/QueryPage.jsx
  - backend/app/services/llm_config.py
  - backend/app/api/query.py
  - index.html
tests:
  - backend/tests/test_provider_label.py
  - backend/tests/conftest.py
  - backend/tests/test_error_responses.py
-->

---
### Requirement: Global exception handler preserves CORS

The backend SHALL register an exception handler for the base `Exception` class on the FastAPI application that catches any unhandled exception bubbling out of route handlers, logs the full traceback, and returns an HTTP 500 response whose body matches the unified error response schema with `error_code = "internal_error"`. The handler SHALL be registered in a way that ensures the response passes through user-registered middleware (including `CORSMiddleware`), so the response includes the `Access-Control-Allow-Origin` header for the configured frontend origin.

#### Scenario: Unhandled exception returns CORS-enabled 500

- **WHEN** a route handler raises an arbitrary `Exception` not caught by any local try/except
- **THEN** the response SHALL be HTTP 500 with body `{"detail": {"error_code": "internal_error", "provider": null, "detail": "Internal server error"}}` and SHALL include `Access-Control-Allow-Origin` header equal to the configured frontend origin

#### Scenario: Built-in HTTPException is not intercepted by global handler

- **WHEN** a route handler raises `HTTPException(status_code=404, detail=...)`
- **THEN** FastAPI's default `HTTPException` handler SHALL handle the response and the global `Exception` handler SHALL NOT execute

#### Scenario: Pydantic validation error is not intercepted by global handler

- **WHEN** an incoming request fails Pydantic validation and triggers `RequestValidationError`
- **THEN** FastAPI's default `RequestValidationError` handler SHALL produce the standard 422 response and the global `Exception` handler SHALL NOT execute

#### Scenario: Traceback is logged for unhandled exception

- **WHEN** the global exception handler runs
- **THEN** the handler SHALL emit a log record at ERROR level containing the request method, request path, and full stack trace via `logger.exception`

<!-- @trace
source: friendly-external-api-errors
updated: 2026-05-01
code:
  - backend/app/main.py
  - backend/app/api/shows.py
  - src/i18n.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/errors.py
  - src/QueryPage.jsx
  - backend/app/services/llm_config.py
  - backend/app/api/query.py
  - index.html
tests:
  - backend/tests/test_provider_label.py
  - backend/tests/conftest.py
  - backend/tests/test_error_responses.py
-->
---
### Requirement: Authentication-related configuration via environment variables

The backend configuration object SHALL expose the following authentication-related environment variables: `GOOGLE_CLIENT_ID` (required), `GOOGLE_CLIENT_SECRET` (required), `GOOGLE_REDIRECT_URI` (required), `SESSION_SECRET` (required, used to sign ephemeral OAuth state cookie), `ADMIN_EMAILS` (optional, comma-separated, default empty), `FRONTEND_ORIGIN` (required, comma-separated for multiple values), and `SESSION_TTL_DAYS` (optional integer, default 14).

#### Scenario: Missing required auth env var prevents startup

- **WHEN** the backend process starts without `GOOGLE_CLIENT_ID` set in the environment
- **THEN** the application SHALL fail to start and SHALL log a descriptive error naming the missing variable

#### Scenario: Empty ADMIN_EMAILS is permitted

- **WHEN** the backend starts with `ADMIN_EMAILS` unset or empty
- **THEN** the application SHALL start successfully
- **AND** no email SHALL be auto-promoted to `admin` on first login

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

<!-- @trace
source: post-auth-ui-and-cleanup
updated: 2026-05-02
code:
  - src/App.jsx
  - src/QueueTab.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - src/ReleaseLogPage.jsx
  - backend/app/main.py
  - index.html
  - src/AuthContext.jsx
  - src/PodcastSelect.jsx
  - backend/app/api/stats.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/stats.py
  - src/i18n.jsx
tests:
  - backend/tests/test_admin_stats.py
  - backend/tests/test_queue_reorder.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_cron_tick_stale.py
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
  - backend/tests/test_queue_cancel.py
-->

---
### Requirement: Web service requires Google OAuth and session env at startup

The FastAPI application defined in `app.main` SHALL fail to start when any of `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, or `SESSION_SECRET` is unset or empty. The check SHALL run inside the FastAPI lifespan startup handler before any router becomes reachable. Worker, dispatcher, beat, and other entrypoints that do not import `app.main` SHALL NOT be subject to this check.

#### Scenario: Web service refuses to start without GOOGLE_CLIENT_ID

- **WHEN** the FastAPI app's lifespan startup runs and `GOOGLE_CLIENT_ID` is empty or unset
- **THEN** the lifespan handler SHALL raise `RuntimeError` naming the missing variable
- **AND** the application SHALL NOT serve any HTTP request

#### Scenario: Worker entrypoints start without web-only env

- **WHEN** the worker, dispatcher, or beat process starts and `GOOGLE_CLIENT_ID` is unset
- **THEN** the process SHALL initialize successfully and accept Celery tasks (worker) or polling cycles (dispatcher) or beat ticks (beat)
- **AND** no `RuntimeError` related to OAuth env SHALL be raised

##### Example: env validation matrix

| Process | GOOGLE_CLIENT_ID | Expected outcome |
| ------- | ---------------- | ---------------- |
| backend | set | start |
| backend | empty | RuntimeError on lifespan startup |
| worker | empty | start |
| dispatcher | empty | start |
| beat | empty | start |

<!-- @trace
source: deploy-resilience
updated: 2026-05-02
-->

<!-- @trace
source: deploy-resilience
updated: 2026-05-03
code:
  - backend/app/main.py
  - backend/app/workers/cron_tick.py
  - backend/app/workers/throttle.py
  - backend/app/workers/celery_app.py
  - backend/app/workers/tasks.py
  - backend/app/workers/lifecycle.py
  - backend/app/api/queue.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/config.py
tests:
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_worker_lifecycle.py
  - backend/tests/test_web_service_env_validation.py
  - backend/tests/test_force_cancel_throttle.py
  - backend/tests/test_queue_cancel.py
-->