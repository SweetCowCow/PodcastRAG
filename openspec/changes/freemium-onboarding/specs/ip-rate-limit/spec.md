## ADDED Requirements

### Requirement: Per-IP daily rate limit on public search endpoint

The system SHALL enforce a per-IP daily rate limit on the public segment search endpoint using a Redis counter. The limit threshold SHALL be configurable via setting `ip_search_rate_limit_per_day` (default 20, env `IP_SEARCH_RATE_LIMIT_PER_DAY`). The counter key SHALL be `rl:search:ip:{client_ip}:{YYYYMMDD}` where `YYYYMMDD` is the current UTC date and `client_ip` is the value of the `X-Forwarded-For` request header (first IP if comma-separated) or, if absent, `request.client.host`. On each public-search request from an unauthenticated caller, the system SHALL `INCR` the counter; if the result equals 1, SHALL also `EXPIRE` the key to 86400 seconds. If after `INCR` the counter exceeds the configured limit, the system SHALL reject the request with HTTP 429 and the response body SHALL be `{"error_code": "ip_rate_limited", "detail": "已達今日免費搜尋上限，請登入繼續使用", "limit": <N>, "reset_at_utc": "<YYYY-MM-DDT00:00:00Z>"}` where `reset_at_utc` is the next UTC midnight.

#### Scenario: First request of the day is allowed and sets EXPIRE

- **GIVEN** an unauthenticated visitor whose IP has no Redis counter for today
- **AND** `ip_search_rate_limit_per_day = 20`
- **WHEN** the visitor calls the public search endpoint
- **THEN** the Redis key `rl:search:ip:{ip}:{YYYYMMDD}` SHALL be set to 1
- **AND** the key SHALL have a TTL of approximately 86400 seconds
- **AND** the request SHALL be processed

#### Scenario: Request below limit is allowed

- **GIVEN** the counter for IP=`1.2.3.4` for today is 5
- **AND** `ip_search_rate_limit_per_day = 20`
- **WHEN** the visitor calls the public search endpoint
- **THEN** the counter SHALL become 6
- **AND** the request SHALL be processed

#### Scenario: Request equal to limit is the last allowed

- **GIVEN** the counter for IP=`1.2.3.4` for today is 19
- **AND** `ip_search_rate_limit_per_day = 20`
- **WHEN** the visitor calls the public search endpoint
- **THEN** the counter SHALL become 20
- **AND** the request SHALL still be processed (the limit is inclusive of the Nth call)

#### Scenario: Request beyond limit is rejected with 429

- **GIVEN** the counter for IP=`1.2.3.4` for today is already 20
- **AND** `ip_search_rate_limit_per_day = 20`
- **WHEN** the visitor calls the public search endpoint
- **THEN** the counter SHALL become 21
- **AND** the response SHALL be HTTP 429 with body `{"error_code": "ip_rate_limited", ...}`
- **AND** no embedding API SHALL be called

#### Scenario: Authenticated user is not subject to IP rate limit

- **GIVEN** the counter for IP=`1.2.3.4` is at the limit
- **WHEN** an authenticated user from the same IP calls the public search endpoint
- **THEN** the request SHALL be processed
- **AND** the IP counter SHALL NOT be incremented

#### Scenario: X-Forwarded-For header is honored

- **GIVEN** a request reaches the backend with header `X-Forwarded-For: 8.8.8.8, 10.0.0.1`
- **WHEN** the rate limiter resolves the client IP
- **THEN** the counter key SHALL use `8.8.8.8` (the first IP in the header)

#### Scenario: Counter key uses UTC date and resets at UTC midnight

- **GIVEN** at 23:55 UTC on 2026-05-04 the counter `rl:search:ip:1.2.3.4:20260504` is at 20
- **WHEN** at 00:01 UTC on 2026-05-05 the same IP calls the endpoint
- **THEN** the counter `rl:search:ip:1.2.3.4:20260505` SHALL be created (set to 1) and the request allowed
- **AND** the previous day's counter SHALL be untouched (will expire on its own TTL)

##### Example: limit values

| limit | calls today | request N | response |
|-------|-------------|-----------|----------|
| 20 | 0 | 1st | 200, counter=1 |
| 20 | 19 | 20th | 200, counter=20 |
| 20 | 20 | 21st | 429, counter=21 |
| 5  | 5  | 6th  | 429, counter=6  |

### Requirement: optional_auth_with_ip_limit FastAPI dependency

The backend SHALL provide a FastAPI dependency `optional_auth_with_ip_limit` that resolves to either an authenticated `User` or `None`. The dependency SHALL: (a) attempt to resolve the session cookie; if a valid active session exists, SHALL return the resolved `User`; (b) if no valid session, SHALL invoke the per-IP rate limit check from this capability; if the limit is not exceeded SHALL return `None`; if the limit is exceeded SHALL raise `HTTPException(status_code=429, detail={...ip_rate_limited body...})`.

#### Scenario: Authenticated user bypasses IP check

- **GIVEN** a request with a valid session cookie for user A
- **WHEN** an endpoint depends on `optional_auth_with_ip_limit`
- **THEN** the dependency SHALL return user A's `User` row
- **AND** the IP rate limit counter SHALL NOT be incremented

#### Scenario: Anonymous request under limit returns None

- **GIVEN** a request with no session cookie
- **AND** the IP counter is below the daily limit
- **WHEN** an endpoint depends on `optional_auth_with_ip_limit`
- **THEN** the dependency SHALL return `None`
- **AND** the IP counter SHALL be incremented by 1

#### Scenario: Anonymous request over limit raises 429

- **GIVEN** a request with no session cookie
- **AND** the IP counter is already at the daily limit
- **WHEN** an endpoint depends on `optional_auth_with_ip_limit`
- **THEN** the dependency SHALL raise `HTTPException` with status 429 and the structured body
- **AND** the route handler SHALL NOT execute

#### Scenario: Expired session falls through to IP path

- **GIVEN** a request with a session cookie whose underlying session row has `expires_at < now()`
- **WHEN** an endpoint depends on `optional_auth_with_ip_limit`
- **THEN** the expired session SHALL be treated as no session
- **AND** the dependency SHALL apply the IP rate limit (return `None` if under, 429 if over)
