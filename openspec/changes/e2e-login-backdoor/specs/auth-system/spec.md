## ADDED Requirements

### Requirement: E2E login backdoor endpoint (env-gated, audit-logged)

The backend SHALL expose an `GET /auth/_e2e_login?token=<TOKEN>` endpoint that issues a session cookie for `ADMIN_EMAILS[0]` when called with a valid token. The endpoint SHALL be registered ONLY when the `E2E_LOGIN_TOKEN` environment variable is non-empty; when unset, the endpoint MUST NOT be registered and requests to its path MUST return HTTP 404 indistinguishably from any other unmapped path. Token comparison SHALL use `hmac.compare_digest` against `E2E_LOGIN_TOKEN`. Configured tokens SHALL be at least 32 characters; configurations with shorter tokens MUST cause backend startup to fail.

#### Scenario: Disabled deployment hides the route entirely

- **WHEN** the backend starts with `E2E_LOGIN_TOKEN` unset or empty
- **THEN** the application SHALL NOT register the `/auth/_e2e_login` route
- **AND** any HTTP request to `GET /auth/_e2e_login` SHALL return HTTP 404 with no response body distinguishing this path from other unmapped paths

#### Scenario: Valid token issues short-lived admin session

- **GIVEN** `E2E_LOGIN_TOKEN` is set to a 64-character random string and `ADMIN_EMAILS[0]` is `admin@example.com`
- **WHEN** the client calls `GET /auth/_e2e_login?token=<correct-token>`
- **THEN** the response SHALL be HTTP 302 with a `Set-Cookie` header containing the session cookie
- **AND** the resulting session SHALL be bound to the user matching `ADMIN_EMAILS[0]`
- **AND** the session expiry SHALL be exactly 15 minutes from issuance, regardless of the configured `SESSION_TTL_DAYS` value
- **AND** an audit log entry SHALL be emitted with fields `event=e2e_login_attempt`, `success=true`, `ip`, `user_agent`, `user_email`

#### Scenario: Invalid token returns 401 and logs failure

- **GIVEN** `E2E_LOGIN_TOKEN` is set
- **WHEN** the client calls `GET /auth/_e2e_login?token=<wrong-token>` or omits the token parameter
- **THEN** the response SHALL be HTTP 401
- **AND** no session cookie SHALL be set
- **AND** an audit log entry SHALL be emitted with fields `event=e2e_login_attempt`, `success=false`, `ip`, `user_agent`

#### Scenario: Token comparison resists timing attack

- **WHEN** the backend compares the provided token against `E2E_LOGIN_TOKEN`
- **THEN** the comparison SHALL use `hmac.compare_digest` (constant-time comparison)
- **AND** the implementation SHALL NOT use Python's `==` operator or any short-circuiting comparison on the token bytes

#### Scenario: Startup rejects under-length tokens

- **WHEN** the backend starts with `E2E_LOGIN_TOKEN` set to a value shorter than 32 characters
- **THEN** startup SHALL fail with a configuration error referencing the minimum length requirement

### Requirement: E2E login per-IP failure rate limit

The e2e login endpoint SHALL track failed attempts per source IP in process-local memory. When the same IP accumulates more than 5 failed attempts within a 60-second sliding window, subsequent requests from that IP SHALL be rejected with HTTP 429 for the next 60 seconds without invoking token comparison. Successful attempts SHALL NOT increment the failure counter.

#### Scenario: Sixth failure within 60 seconds is throttled

- **GIVEN** `E2E_LOGIN_TOKEN` is set
- **WHEN** the same source IP makes 5 requests with an invalid token within 60 seconds
- **AND** the same IP makes a 6th request within the next 60 seconds
- **THEN** the 6th request SHALL receive HTTP 429
- **AND** token comparison SHALL NOT be performed for the 6th request
- **AND** an audit log entry SHALL be emitted with `event=e2e_login_rate_limited`, `ip`

#### Scenario: Successful attempts do not consume rate-limit budget

- **GIVEN** `E2E_LOGIN_TOKEN` is set
- **WHEN** an IP makes 10 successful requests within 60 seconds
- **THEN** none SHALL be rate-limited
- **AND** the failure counter for that IP SHALL remain at 0

#### Scenario: Rate-limit window expires

- **GIVEN** an IP has been rate-limited
- **WHEN** 60 seconds pass without further attempts
- **THEN** the next request from that IP SHALL be processed normally (failure counter reset)
