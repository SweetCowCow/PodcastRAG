## MODIFIED Requirements

### Requirement: Adapter interface for provider usage

The backend SHALL expose a uniform adapter interface in `app.services.provider_usage`. Each adapter module SHALL implement the function signature `async def fetch_daily_usage(start: date, end: date) -> list[UsageSnapshot]` where `UsageSnapshot` is a dataclass with fields `(provider: str, model: str | None, date: date, spend_usd: Decimal, raw_payload: dict)`. Adapters SHALL be registered in `provider_usage/__init__.py` `ADAPTERS: dict[str, Callable]` so the collector iterates them generically. The AI Hub adapter SHALL fetch data from the Zeabur GraphQL API at `https://api.zeabur.com/graphql` using the `aihubMonthlyUsage(month: String)` query authenticated via the `ZEABUR_API_TOKEN` environment variable. When the requested date range crosses month boundaries, the adapter SHALL issue one GraphQL request per month and merge results, filtering returned `dailyUsage` entries to those within `[start, end]`. Date ranges spanning more than 6 months SHALL raise `ValueError`.

#### Scenario: AI Hub adapter returns daily usage from GraphQL

- **GIVEN** `ADAPTERS['aihub']` is the Zeabur AI Hub GraphQL adapter
- **AND** `ZEABUR_API_TOKEN` is set
- **WHEN** `await ADAPTERS['aihub'](date(2026, 5, 1), date(2026, 5, 10))` is called
- **THEN** the adapter SHALL POST to `https://api.zeabur.com/graphql` with the `aihubMonthlyUsage(month: "2026-05")` query
- **AND** the return value SHALL be `list[UsageSnapshot]` with provider='aihub' for every snapshot
- **AND** each snapshot's `date` field SHALL fall within `[date(2026,5,1), date(2026,5,10)]`

#### Scenario: OpenAI adapter returns daily usage

- **GIVEN** `ADAPTERS['openai']` is the OpenAI direct adapter
- **WHEN** `await ADAPTERS['openai'](date(2026, 5, 1), date(2026, 5, 10))` is called
- **THEN** the return value SHALL be `list[UsageSnapshot]` with provider='openai' for every snapshot

#### Scenario: AI Hub adapter without token gracefully returns empty

- **GIVEN** AI Hub GraphQL adapter is invoked but `ZEABUR_API_TOKEN` env is unset
- **WHEN** `fetch_daily_usage(...)` runs
- **THEN** the adapter SHALL log a warning "ZEABUR_API_TOKEN not configured, skipping aihub usage fetch"
- **AND** SHALL return an empty list (no exception raised)

#### Scenario: OpenAI adapter without admin key gracefully returns empty

- **GIVEN** OpenAI adapter is invoked but `OPENAI_ORG_ADMIN_KEY` env is unset
- **WHEN** `fetch_daily_usage(...)` runs
- **THEN** the adapter SHALL log a warning "OPENAI_ORG_ADMIN_KEY not configured, skipping"
- **AND** SHALL return an empty list (no exception raised)

#### Scenario: AI Hub adapter splits cross-month range into multiple GraphQL queries

- **GIVEN** `ADAPTERS['aihub']` is the Zeabur AI Hub GraphQL adapter
- **AND** `ZEABUR_API_TOKEN` is set
- **WHEN** `await ADAPTERS['aihub'](date(2026, 4, 29), date(2026, 5, 2))` is called
- **THEN** the adapter SHALL issue exactly 2 GraphQL POST requests (one for month "2026-04", one for "2026-05")
- **AND** SHALL return only snapshots whose `date` falls within `[date(2026,4,29), date(2026,5,2)]`

#### Scenario: AI Hub adapter rejects oversize date range

- **WHEN** `await ADAPTERS['aihub'](date(2025, 1, 1), date(2026, 5, 1))` is called (spanning more than 6 months)
- **THEN** the adapter SHALL raise `ValueError` with message containing "Date range too large"

#### Scenario: AI Hub adapter raises on 5xx after retry exhaustion

- **GIVEN** `ZEABUR_API_TOKEN` is set
- **AND** the GraphQL endpoint returns HTTP 503 for every attempt
- **WHEN** `fetch_daily_usage(date(2026,5,1), date(2026,5,2))` runs
- **THEN** the adapter SHALL retry up to 3 attempts with exponential backoff
- **AND** after exhausting retries SHALL raise `httpx.HTTPStatusError` (no fail-open behavior)

#### Scenario: AI Hub adapter raises immediately on 4xx

- **GIVEN** `ZEABUR_API_TOKEN` is set to an invalid value
- **AND** the GraphQL endpoint returns HTTP 401
- **WHEN** `fetch_daily_usage(...)` runs
- **THEN** the adapter SHALL raise `httpx.HTTPStatusError` without retry

#### Scenario: AI Hub adapter raises when GraphQL response contains errors field

- **GIVEN** the GraphQL endpoint returns HTTP 200 with body `{"data": null, "errors": [{"message": "..."}]}`
- **WHEN** `fetch_daily_usage(...)` runs
- **THEN** the adapter SHALL raise `RuntimeError` with message containing "GraphQL errors"
