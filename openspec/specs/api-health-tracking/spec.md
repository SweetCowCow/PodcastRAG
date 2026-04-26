# api-health-tracking Specification

## Purpose

TBD - created by archiving change 'transcription-progress-visibility'. Update Purpose after archive.

## Requirements

### Requirement: External API health tracker service

The backend SHALL expose an `api_health` tracker service that records a bounded window of recent external-API call events (time, success flag, duration, and a normalised error category on failure) for each known API name, and SHALL be invoked at every external-API call site so that a single source of truth for "most recent call state" exists regardless of which module issues the call.

The tracker SHALL persist events in Redis using list keys of the form `api_health:{api_name}` where `{api_name}` is one of `openai_whisper`, `openai_chat`, `openai_embedding`, with new events prepended via `LPUSH` and the list trimmed to the 20 most recent entries via `LTRIM 0 19`. Each event SHALL be stored as JSON with the fields `ts_ms` (integer epoch milliseconds), `ok` (boolean), `duration_ms` (non-negative integer), `error_category` (string or null), and `http_status` (integer or null). The tracker SHALL set a key TTL of 7 days on first write so dormant APIs do not occupy memory indefinitely.

The tracker SHALL expose a `record(api_name, ok, duration_ms, error_category, http_status)` function for writers and a `get_recent(api_name, limit)` function for readers that returns events in descending timestamp order. The tracker SHALL fail open: any Redis exception during `record` SHALL be caught, logged at WARNING level, and SHALL NOT propagate to the caller; any Redis exception during `get_recent` SHALL yield an empty list and set a degraded-mode flag that the reading endpoint can surface.

#### Scenario: Successful call recorded

- **WHEN** an OpenAI Whisper call completes successfully and the caller invokes `record("openai_whisper", ok=True, duration_ms=432, error_category=None, http_status=200)`
- **THEN** a JSON event MATCHING `{"ts_ms": <now>, "ok": true, "duration_ms": 432, "error_category": null, "http_status": 200}` SHALL be prepended to Redis list `api_health:openai_whisper`, the list SHALL be trimmed to at most 20 entries, and the key SHALL have TTL of 7 days (604800 seconds)

#### Scenario: Failed call recorded with category

- **WHEN** an OpenAI Whisper call raises `openai.RateLimitError` whose response payload contains `"code": "insufficient_quota"` and the caller invokes `record("openai_whisper", ok=False, duration_ms=120, error_category="quota_exceeded", http_status=429)`
- **THEN** a JSON event `{"ts_ms": <now>, "ok": false, "duration_ms": 120, "error_category": "quota_exceeded", "http_status": 429}` SHALL be prepended to `api_health:openai_whisper`

#### Scenario: Tracker failure does not break the API call

- **WHEN** `record()` is invoked but Redis is unreachable and raises `redis.ConnectionError`
- **THEN** the tracker SHALL catch the exception, log a WARNING with the api_name and exception type, and return None
- **AND** the caller's surrounding API call SHALL NOT observe any raised exception from the tracker

#### Scenario: Reader returns empty on Redis failure

- **WHEN** `get_recent("openai_chat", 20)` is called while Redis is down
- **THEN** the function SHALL return an empty list without raising
- **AND** SHALL expose a way for the calling endpoint to detect the degraded state (e.g. returning `(events, degraded_flag)` tuple or raising a specific sentinel caught by endpoint handler)


<!-- @trace
source: transcription-progress-visibility
updated: 2026-04-27
code:
  - backend/app/api/admin.py
  - src/Shared.jsx
  - backend/alembic/versions/e3f4a5b6c7d8_add_transcripts_updated_at.py
  - backend/pytest.ini
  - backend/app/schemas/transcription_status.py
  - backend/app/api/shows.py
  - backend/app/services/transcription/openai_provider.py
  - src/AdminPage.jsx
  - src/ExternalApiStatusTab.jsx
  - backend/app/services/api_health.py
  - index.html
  - backend/app/services/rag.py
  - backend/app/schemas/api_health.py
  - backend/app/services/embedding.py
  - backend/app/models/transcript.py
tests:
  - backend/tests/__init__.py
  - backend/tests/test_api_health.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
-->

---
### Requirement: Error classifier produces a stable enumerated category

The `api_health` service SHALL provide a `classify_error(exc, http_status)` function that maps raised exceptions and HTTP status codes to one of exactly six category strings — `quota_exceeded`, `rate_limited`, `auth_error`, `server_error`, `network_error`, `unknown` — so that readers receive a stable enum independent of upstream error message wording.

#### Scenario: Quota exceeded classified

- **WHEN** the exception is `openai.RateLimitError` and its response body parses to `{"error": {"code": "insufficient_quota", ...}}`
- **THEN** `classify_error` SHALL return `"quota_exceeded"`

#### Scenario: Rate limited classified

- **WHEN** the exception is `openai.RateLimitError` and the response body's `error.code` is not `"insufficient_quota"` (or absent)
- **THEN** `classify_error` SHALL return `"rate_limited"`

#### Scenario: Auth error classified

- **WHEN** the exception is `openai.AuthenticationError`, or the HTTP status is 401 or 403
- **THEN** `classify_error` SHALL return `"auth_error"`

#### Scenario: Server error classified

- **WHEN** the HTTP status is between 500 and 599 inclusive (or exception is `openai.APIStatusError` whose `status_code` falls in that range)
- **THEN** `classify_error` SHALL return `"server_error"`

#### Scenario: Network error classified

- **WHEN** the exception is `httpx.TimeoutException`, `httpx.ConnectError`, `asyncio.TimeoutError`, or `openai.APIConnectionError`
- **THEN** `classify_error` SHALL return `"network_error"`

#### Scenario: Unknown error classified

- **WHEN** the exception does not match any of the known types above AND the HTTP status is absent or not in a recognised range
- **THEN** `classify_error` SHALL return `"unknown"`

##### Example: classification table

| Exception / HTTP status                             | Expected category  |
| --------------------------------------------------- | ------------------ |
| `openai.RateLimitError` + code `insufficient_quota` | `quota_exceeded`   |
| `openai.RateLimitError` + code `rate_limit_exceeded`| `rate_limited`     |
| `openai.AuthenticationError`                        | `auth_error`       |
| HTTP 503                                            | `server_error`     |
| `httpx.ConnectError`                                | `network_error`    |
| `ValueError("bad input")`                           | `unknown`          |

<!-- @trace
source: transcription-progress-visibility
updated: 2026-04-27
code:
  - backend/app/api/admin.py
  - src/Shared.jsx
  - backend/alembic/versions/e3f4a5b6c7d8_add_transcripts_updated_at.py
  - backend/pytest.ini
  - backend/app/schemas/transcription_status.py
  - backend/app/api/shows.py
  - backend/app/services/transcription/openai_provider.py
  - src/AdminPage.jsx
  - src/ExternalApiStatusTab.jsx
  - backend/app/services/api_health.py
  - index.html
  - backend/app/services/rag.py
  - backend/app/schemas/api_health.py
  - backend/app/services/embedding.py
  - backend/app/models/transcript.py
tests:
  - backend/tests/__init__.py
  - backend/tests/test_api_health.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
-->