# backend-core Specification

## Purpose

TBD - created by archiving change 'backend-api'. Update Purpose after archive.

## Requirements

### Requirement: FastAPI application entrypoint

The backend SHALL provide a FastAPI application instance as the main entrypoint, configured with CORS middleware to allow requests from the frontend origin.

#### Scenario: Application starts successfully

- **WHEN** the backend process starts with valid environment variables
- **THEN** the FastAPI application SHALL be accessible and return HTTP 200 on the health endpoint

#### Scenario: CORS allows frontend origin

- **WHEN** a request arrives from the configured frontend origin
- **THEN** the server SHALL include the appropriate CORS headers in the response


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