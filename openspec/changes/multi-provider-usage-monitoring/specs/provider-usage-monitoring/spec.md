## ADDED Requirements

### Requirement: Provider usage snapshot table

The backend SHALL maintain a `provider_usage_snapshot` table with columns: `id` (UUID PK), `provider` (string: `aihub`, `openai`, plus future identifiers), `model` (nullable string), `date` (date), `spend_usd` (numeric(10,4)), `raw_payload` (jsonb), `fetched_at` (timestamptz). The table SHALL have a unique constraint on `(provider, model, date)` so re-fetching the same day overwrites rather than duplicates. New providers SHALL be added by inserting rows with new `provider` values without any schema change.

#### Scenario: First fetch inserts row

- **GIVEN** the table has no rows for `(aihub, gpt-4o-mini, 2026-05-10)`
- **WHEN** the usage collector inserts `(aihub, gpt-4o-mini, 2026-05-10, 1.23, {...}, NOW())`
- **THEN** exactly one row SHALL exist with those values

#### Scenario: Re-fetch upserts the row

- **GIVEN** a row `(aihub, gpt-4o-mini, 2026-05-10, 1.23, ...)` already exists
- **WHEN** the collector re-fetches and the new daily total is 2.45
- **THEN** the row SHALL be updated (not duplicated) to `spend_usd=2.45`, `fetched_at=NOW()`

#### Scenario: New provider adds rows without migration

- **GIVEN** a new adapter for `deepgram` is added to the registry
- **WHEN** the collector calls the deepgram adapter and writes its results
- **THEN** rows with `provider='deepgram'` SHALL be inserted into the same table

---

### Requirement: Adapter interface for provider usage

The backend SHALL expose a uniform adapter interface in `app.services.provider_usage`. Each adapter module SHALL implement the function signature `async def fetch_daily_usage(start: date, end: date) -> list[UsageSnapshot]` where `UsageSnapshot` is a dataclass with fields `(provider: str, model: str | None, date: date, spend_usd: Decimal, raw_payload: dict)`. Adapters SHALL be registered in `provider_usage/__init__.py` `ADAPTERS: dict[str, Callable]` so the collector iterates them generically.

#### Scenario: AI Hub adapter returns daily usage

- **GIVEN** `ADAPTERS['aihub']` is the Zeabur AI Hub adapter
- **WHEN** `await ADAPTERS['aihub'](date(2026, 5, 1), date(2026, 5, 10))` is called
- **THEN** the return value SHALL be `list[UsageSnapshot]` with provider='aihub' for every snapshot

#### Scenario: OpenAI adapter returns daily usage

- **GIVEN** `ADAPTERS['openai']` is the OpenAI direct adapter
- **WHEN** `await ADAPTERS['openai'](date(2026, 5, 1), date(2026, 5, 10))` is called
- **THEN** the return value SHALL be `list[UsageSnapshot]` with provider='openai' for every snapshot

#### Scenario: Adapter without admin key gracefully returns empty

- **GIVEN** OpenAI adapter is invoked but `OPENAI_ORG_ADMIN_KEY` env is unset
- **WHEN** `fetch_daily_usage(...)` runs
- **THEN** the adapter SHALL log a warning "OPENAI_ORG_ADMIN_KEY not configured, skipping"
- **AND** SHALL return an empty list (no exception raised)

---

### Requirement: Hourly usage collector beat task

The backend SHALL register a Celery Beat schedule entry `usage-collector` running every hour on the hour (cron `0 * * * *`). The handler SHALL iterate every adapter in `ADAPTERS`, call `fetch_daily_usage(start=yesterday, end=today)`, and upsert each `UsageSnapshot` into `provider_usage_snapshot`. If one adapter raises, the collector SHALL log the error and continue with remaining adapters (per-adapter isolation).

#### Scenario: All adapters succeed

- **GIVEN** ADAPTERS = {aihub, openai} both healthy
- **WHEN** the usage-collector beat task runs
- **THEN** rows for both providers covering yesterday and today SHALL be upserted
- **AND** the handler SHALL log success counts per provider

#### Scenario: One adapter fails, other succeeds

- **GIVEN** the openai adapter raises `httpx.TimeoutException` but aihub succeeds
- **WHEN** the usage-collector beat task runs
- **THEN** aihub rows SHALL still be written
- **AND** the openai failure SHALL be logged with `exc_info=True`
- **AND** the handler SHALL exit normally (no Celery retry, the next hourly tick will try openai again)

---

### Requirement: Daily usage threshold alert beat task

The backend SHALL register a Celery Beat schedule entry `usage-alert` running daily at 09:00 Asia/Taipei (cron `0 1 * * *` in UTC = 09:00 Taipei). The handler SHALL evaluate per provider:

1. Compute current calendar month accumulated spend: `SELECT SUM(spend_usd) FROM provider_usage_snapshot WHERE provider=:p AND date_trunc('month', date) = date_trunc('month', NOW())`
2. Compare against `provider_budget_usd_monthly[provider]` config (v1 hardcoded: aihub=80, openai=30)
3. If ratio >= 0.95 → red severity; else if ratio >= 0.80 → yellow severity; else no alert
4. Per provider per severity per UTC day, send at most one ZSend alert. Track in `usage_alert_log` table `(provider, severity, alerted_date PK)` to dedupe.

The alert email SHALL contain provider name, accumulated spend, budget, ratio percentage, top 3 models by spend this month, link hint to admin UI.

#### Scenario: 80% triggers yellow alert

- **GIVEN** aihub provider has accumulated $65 of $80 monthly budget (81%)
- **AND** no yellow alert was sent today for aihub
- **WHEN** the usage-alert beat task runs
- **THEN** exactly one ZSend yellow alert SHALL be sent for aihub
- **AND** `usage_alert_log` SHALL have row `(aihub, yellow, 2026-05-10)`

#### Scenario: 95% triggers red alert

- **GIVEN** aihub accumulated $77 of $80 (96%)
- **WHEN** the task runs
- **THEN** one ZSend red alert SHALL be sent
- **AND** no yellow alert SHALL be sent (red supersedes)

#### Scenario: Already-alerted today not re-alerted

- **GIVEN** aihub yellow alert was sent earlier today (`usage_alert_log` has row)
- **AND** ratio is still 82%
- **WHEN** the task runs
- **THEN** no new alert SHALL be sent

#### Scenario: Below 80% no alert

- **GIVEN** aihub accumulated $40 of $80 (50%)
- **WHEN** the task runs
- **THEN** no alert SHALL be sent

---

### Requirement: Admin REST endpoint for usage data

The backend SHALL expose admin-only REST endpoints (require admin role + CSRF):

- `GET /admin/provider-usage/daily?start=<date>&end=<date>` returns JSON list of `(provider, model, date, spend_usd)` rows in the range
- `GET /admin/provider-usage/monthly` returns JSON `{provider: {budget_usd, accumulated_usd, ratio, top_models: [{model, spend_usd}]}}` for current calendar month, all providers

Times in ISO 8601 UTC. Frontend SHALL convert to Asia/Taipei for display.

#### Scenario: Daily endpoint returns 30-day data

- **WHEN** admin calls `GET /admin/provider-usage/daily?start=2026-04-11&end=2026-05-10`
- **THEN** the response SHALL be a 200 JSON array containing rows for both providers in that range

#### Scenario: Monthly endpoint returns ratios

- **GIVEN** aihub accumulated $35 of $80 budget, openai $10 of $30
- **WHEN** admin calls `GET /admin/provider-usage/monthly`
- **THEN** the response SHALL include `aihub.ratio = 0.4375` and `openai.ratio = 0.3333`
- **AND** `top_models` SHALL list each provider's top 3 spending models for the month

#### Scenario: Non-admin gets 403

- **WHEN** a non-admin user calls either endpoint
- **THEN** the response SHALL be 403 Forbidden

---

### Requirement: Admin UI shows usage chart and budget banner

The admin frontend SHALL add a new tab "服務用量" (Service Usage) at route `page='admin-provider-usage'`, accessible from the admin sidebar nav. The tab SHALL render:

1. Top banner per provider:
   - Yellow banner if `ratio >= 0.80 && < 0.95` with text "<provider> 用量已達 <ratio>%（$<spend> / $<budget>）— 留意是否需要充值"
   - Red banner if `ratio >= 0.95` with text "<provider> 用量已達 <ratio>% — 請立即至 Zeabur / OpenAI 後台充值，否則服務將中斷"
2. Per-provider summary card: monthly budget, accumulated spend, ratio bar, top 3 models with $ amounts
3. 30-day stacked SVG bar chart: x-axis = date (Asia/Taipei), y-axis = spend USD, one stacked column per day per provider, hover SHALL show tooltip with date + per-provider $ breakdown

The UI SHALL refresh every 60 seconds via polling. All text in 繁體中文 + 英文 i18n key.

The 操作 area SHALL NOT contain any auto-recharge button. Instead, the red banner SHALL contain a static link "前往 Zeabur AI Hub" / "前往 OpenAI dashboard" opening in new tab.

#### Scenario: Yellow ratio shows yellow banner

- **GIVEN** aihub ratio is 0.82
- **WHEN** admin views the tab
- **THEN** a yellow banner SHALL appear at top with text containing "aihub 用量已達 82%"

#### Scenario: Red ratio shows red banner with external link

- **GIVEN** aihub ratio is 0.97
- **WHEN** admin views the tab
- **THEN** a red banner SHALL appear with text containing "aihub 用量已達 97%"
- **AND** a link "前往 Zeabur AI Hub" SHALL be present opening `https://dash.zeabur.com/` in new tab

#### Scenario: 30-day chart hover tooltip

- **GIVEN** the chart shows 30 daily bars per provider
- **WHEN** admin hovers over the 2026-05-09 bar
- **THEN** a tooltip SHALL appear with text "2026-05-09 台北 — aihub: $35.16 / openai: $0.50"

#### Scenario: No auto-recharge button rendered

- **WHEN** admin views the tab regardless of ratio
- **THEN** no button labelled "auto-recharge" / "自動充值" / "啟用扣款" SHALL be present
