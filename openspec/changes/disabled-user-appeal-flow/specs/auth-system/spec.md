## ADDED Requirements

### Requirement: ACCOUNT_DISABLED callback redirects with appeal availability flag for SPA handling

When the OAuth callback rejects a login because the resolved user has `users.status='disabled'`, the callback handler SHALL respond with HTTP 302 redirect to `<frontend_origin>/?auth_error=account_disabled&appeal_enabled=<bool>&email=<urlencoded_email>` instead of raising raw HTTP 403 JSON. The reason is that the OAuth callback URL is loaded by the browser directly (the user is mid-flow from Google's consent screen), so a 403 JSON response would dump unparseable JSON in the browser viewport and bypass the SPA entirely. By using a redirect with query parameters, the SPA at the frontend root SHALL detect the parameters, render the Lock card disabled state, and surface the appeal CTA — preserving the user-facing flow.

The `appeal_enabled` query parameter value SHALL come from the `ACCOUNT_APPEAL_ENABLED` env var setting (default `true`). When the SPA reads `appeal_enabled=false`, it SHALL NOT show the appeal CTA, only the contact-admin guidance text.

The underlying error contract (`error=account_disabled` + `appeal_enabled` flag) SHALL also be exposed via the shared `ErrorResponse` schema builder so that any non-OAuth-callback caller (e.g. session re-validation API) returning 403 `account_disabled` SHALL include the same JSON body `{"error":"account_disabled","appeal_enabled":<bool>}`. This keeps the API contract uniform while letting the OAuth callback path adapt to the browser-redirect requirement.

#### Scenario: Disabled user OAuth callback redirects with appeal_enabled flag

- **GIVEN** a user whose `users.status='disabled'`
- **AND** `ACCOUNT_APPEAL_ENABLED` is unset or `true`
- **WHEN** the user completes the Google OAuth flow and Google redirects to `/auth/google/callback`
- **THEN** the response SHALL be HTTP 302 redirect to `<frontend_origin>/?auth_error=account_disabled&appeal_enabled=true&email=<urlencoded user email>`
- **AND** no session cookie SHALL be set

#### Scenario: Appeals disabled by configuration still redirects with flag=false

- **GIVEN** a user whose `users.status='disabled'`
- **AND** `ACCOUNT_APPEAL_ENABLED=false` is set in the environment
- **WHEN** the user completes the Google OAuth flow
- **THEN** the response SHALL be HTTP 302 redirect with `appeal_enabled=false` in the query string
- **AND** the SPA SHALL render the Lock card disabled state without the appeal CTA

#### Scenario: Non-callback 403 paths retain JSON body contract

- **GIVEN** a programmatic API caller invokes an endpoint that returns 403 `account_disabled` via the shared `ErrorResponse` builder (not the OAuth callback)
- **WHEN** the endpoint resolves and emits the error
- **THEN** the response SHALL be HTTP 403 with JSON body `{"error":"account_disabled","appeal_enabled":<bool>}`
- **AND** the `appeal_enabled` field SHALL match the env setting
