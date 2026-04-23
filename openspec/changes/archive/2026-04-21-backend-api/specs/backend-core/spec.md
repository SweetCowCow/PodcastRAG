## ADDED Requirements

### Requirement: FastAPI application entrypoint

The backend SHALL provide a FastAPI application instance as the main entrypoint, configured with CORS middleware to allow requests from the frontend origin.

#### Scenario: Application starts successfully

- **WHEN** the backend process starts with valid environment variables
- **THEN** the FastAPI application SHALL be accessible and return HTTP 200 on the health endpoint

#### Scenario: CORS allows frontend origin

- **WHEN** a request arrives from the configured frontend origin
- **THEN** the server SHALL include the appropriate CORS headers in the response

### Requirement: Health check endpoint

The backend SHALL expose a `GET /health` endpoint that returns the current health status of the service.

#### Scenario: Service is healthy

- **WHEN** `GET /health` is called and the database connection is reachable
- **THEN** the response SHALL be HTTP 200 with JSON body `{"status": "ok", "database": "connected"}`

#### Scenario: Database is unreachable

- **WHEN** `GET /health` is called and the database connection fails
- **THEN** the response SHALL be HTTP 503 with JSON body `{"status": "error", "database": "disconnected"}`

### Requirement: Configuration management via environment variables

The backend SHALL read all configuration values from environment variables using pydantic-settings, with no hardcoded secrets or connection strings in source code.

#### Scenario: Valid configuration loaded

- **WHEN** all required environment variables are present in `.env` or the environment
- **THEN** the application SHALL start and all settings SHALL be accessible via the settings object

#### Scenario: Missing required environment variable

- **WHEN** a required environment variable (e.g., `DATABASE_URL`) is absent
- **THEN** the application SHALL fail to start and log a descriptive error indicating which variable is missing

### Requirement: Async database session management

The backend SHALL provide an async SQLAlchemy session factory, injected via FastAPI dependency injection, that opens a session per request and closes it after the response.

#### Scenario: Session is available during request

- **WHEN** a route handler declares a `db: AsyncSession` dependency
- **THEN** an async database session SHALL be injected and committed on success

#### Scenario: Session is closed on exception

- **WHEN** a route handler raises an unhandled exception
- **THEN** the session SHALL be rolled back and closed without leaking the connection
