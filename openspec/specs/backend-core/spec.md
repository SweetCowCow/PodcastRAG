# backend-core Specification

## Purpose

TBD - created by archiving change 'backend-api'. Update Purpose after archive.

## Requirements

### Requirement: FastAPI application entrypoint

The backend SHALL provide a FastAPI application instance as the main entrypoint, configured with CORS middleware to allow requests from the frontend origin, and SHALL register a global exception handler for `Exception` that returns the unified error response schema with CORS headers preserved.

#### Scenario: Application starts successfully

- **WHEN** the backend process starts with valid environment variables
- **THEN** the FastAPI application SHALL be accessible and return HTTP 200 on the health endpoint

#### Scenario: CORS allows frontend origin

- **WHEN** a request arrives from the configured frontend origin
- **THEN** the server SHALL include the appropriate CORS headers in the response

#### Scenario: Global exception handler is registered at startup

- **WHEN** the FastAPI application is created
- **THEN** an exception handler bound to the base `Exception` class SHALL be registered on the application instance before any router is included


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

The backend SHALL read all configuration values from environment variables using pydantic-settings, with no hardcoded secrets or connection strings in source code.

#### Scenario: Valid configuration loaded

- **WHEN** all required environment variables are present in `.env` or the environment
- **THEN** the application SHALL start and all settings SHALL be accessible via the settings object

#### Scenario: Missing required environment variable

- **WHEN** a required environment variable (e.g., `DATABASE_URL`) is absent
- **THEN** the application SHALL fail to start and log a descriptive error indicating which variable is missing


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