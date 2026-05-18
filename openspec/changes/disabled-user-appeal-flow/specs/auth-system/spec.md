## ADDED Requirements

### Requirement: ACCOUNT_DISABLED response signals appeal availability to the frontend

When the OAuth callback rejects a login with HTTP 403 `account_disabled`, the response body SHALL include the field `appeal_enabled: true` to signal to the frontend that the appeal endpoint (`POST /auth/appeal`) is available. The backend SHALL be able to disable appeals by setting `appeal_enabled: false` via configuration (env var `ACCOUNT_APPEAL_ENABLED`, default `true`). When disabled, the frontend SHALL NOT show the appeal CTA.

#### Scenario: Disabled user login returns appeal_enabled flag

- **GIVEN** a user whose `users.status='disabled'`
- **AND** `ACCOUNT_APPEAL_ENABLED` is unset or `true`
- **WHEN** the user completes the Google OAuth flow
- **THEN** the response SHALL be HTTP 403 with JSON body `{"error":"account_disabled","appeal_enabled":true}`

#### Scenario: Appeals disabled by configuration

- **GIVEN** a user whose `users.status='disabled'`
- **AND** `ACCOUNT_APPEAL_ENABLED=false` is set in the environment
- **WHEN** the user completes the Google OAuth flow
- **THEN** the response SHALL be HTTP 403 with JSON body `{"error":"account_disabled","appeal_enabled":false}`
