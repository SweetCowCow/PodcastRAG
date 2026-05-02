## ADDED Requirements

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

## MODIFIED Requirements

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
