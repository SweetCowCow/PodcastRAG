## ADDED Requirements

### Requirement: Service circuit state table

The backend SHALL maintain a `service_circuit_state` table with columns: `provider_id` (string PK; allowed values: `openai`, `aihub`, `zsend`), `task_type` (nullable string; reserved for future per-task-type granularity, write NULL in v1), `state` (enum: `closed` | `open`; default `closed`), `opened_at` (nullable timestamptz), `paused_task_count` (int default 0; tracks how many tasks have hit the open circuit since `opened_at`), `last_probe_at` (nullable timestamptz), `last_probe_result` (nullable enum: `success` | `failure`), `manual_resumed_by` (nullable string), `manual_resumed_at` (nullable timestamptz). On startup the backend SHALL ensure exactly one row per known provider exists, default `state='closed'`.

#### Scenario: Default rows created on startup

- **WHEN** the backend startup hook runs against an empty `service_circuit_state` table
- **THEN** three rows SHALL exist: `('openai', NULL, 'closed', ...)`, `('aihub', NULL, 'closed', ...)`, `('zsend', NULL, 'closed', ...)`

#### Scenario: Existing rows preserved on startup

- **GIVEN** the table already contains `('openai', NULL, 'open', opened_at=2 hours ago, paused_task_count=42, ...)`
- **WHEN** the backend startup hook runs
- **THEN** the existing `openai` row SHALL be preserved unchanged
- **AND** missing provider rows SHALL be added as `closed`

---

### Requirement: Circuit breaker opens on permanent error threshold

When `task_failure_log` records a row with `failure_type='permanent'` AND `provider_id IS NOT NULL`, the writing code path SHALL evaluate the circuit breaker rule:

1. Count rows in `task_failure_log` where `provider_id = <this row's provider_id>` AND `failure_type='permanent'` AND `failed_at > NOW() - INTERVAL '5 minutes'`.
2. If count >= 3 AND `service_circuit_state` row for this provider has `state='closed'` → atomically transition the provider's row to `state='open'`, `opened_at=NOW()`, `paused_task_count=0`, using `UPDATE ... WHERE state='closed' RETURNING ...` (no-op if a concurrent transition already happened).
3. If the atomic transition succeeded, send a ZSend email to `settings.zsend_admin_to_email` containing: provider_id, opened_at (Asia/Taipei), failure count, last 3 error messages, expected behaviour ("all tasks for this provider will pause until manual resume or sentinel probe succeeds"), admin UI link.

#### Scenario: 3rd permanent error within 5 minutes opens circuit

- **GIVEN** the `openai` provider has 2 permanent failures within the last 5 minutes and `service_circuit_state.openai.state = 'closed'`
- **WHEN** a 3rd `transcribe_episode` task fails with HTTP 402 (permanent, openai)
- **THEN** `service_circuit_state.openai` SHALL be UPDATEd to `state='open'`, `opened_at=NOW()`, `paused_task_count=0`
- **AND** exactly one ZSend email SHALL be sent

#### Scenario: 2 permanent errors does not open circuit

- **GIVEN** 1 prior permanent failure for `openai` within 5 minutes
- **WHEN** a 2nd `openai` permanent error is logged
- **THEN** `service_circuit_state.openai.state` SHALL remain `closed`
- **AND** no ZSend email SHALL be sent

#### Scenario: Concurrent 3rd-error race ends with single open transition

- **GIVEN** 2 prior permanent failures for `openai` and 2 worker processes simultaneously hit a 3rd permanent failure
- **WHEN** both worker processes try to open the circuit
- **THEN** exactly one `UPDATE ... WHERE state='closed' RETURNING ...` SHALL succeed
- **AND** exactly one ZSend email SHALL be sent

---

### Requirement: Tasks check circuit state on entry and self-retry when open

Each Celery task that uses an external provider (`transcribe_episode` for openai, `classify_episode_topics` for aihub, `generate_episode_summary` for aihub, `send_quota_digest` for zsend, `send_eval_reminder` for zsend) SHALL call `circuit_breaker.is_open(provider_id) -> bool` before any external I/O. If `True`:

1. Increment `service_circuit_state.<provider_id>.paused_task_count` by 1.
2. Raise `self.retry(countdown=300, max_retries=None)` so Celery puts the task back on the broker for delivery 5 minutes later.

The check SHALL run inside the same transaction as worker entry idempotency (so a single short DB round trip covers both). When `state='closed'`, the task proceeds normally.

#### Scenario: Open circuit causes task to self-retry

- **GIVEN** `service_circuit_state.openai.state='open'`
- **WHEN** the worker picks up a `transcribe_episode` task
- **THEN** the task SHALL increment `paused_task_count` by 1
- **AND** the task SHALL raise `self.retry(countdown=300, max_retries=None)`
- **AND** the task SHALL NOT call the OpenAI client

#### Scenario: Closed circuit lets task proceed

- **GIVEN** `service_circuit_state.openai.state='closed'`
- **WHEN** the worker picks up a `transcribe_episode` task
- **THEN** the task SHALL skip the retry path
- **AND** the task SHALL proceed to call the OpenAI client (subject to existing throttle / per-show lock)

#### Scenario: paused_task_count tracks pause volume

- **GIVEN** `service_circuit_state.openai.state='open'` with `paused_task_count=5`
- **WHEN** 7 more `transcribe_episode` tasks check the circuit and self-retry
- **THEN** `paused_task_count` SHALL equal 12

---

### Requirement: Sentinel probe attempts auto-recovery every 30 minutes

The backend SHALL register a Celery Beat schedule entry `circuit-probe` running every 30 minutes (cron `*/30 * * * *`). The handler SHALL iterate `service_circuit_state` rows where `state='open'`. For each open provider, the handler SHALL invoke a provider-specific probe function:

- `openai` probe: `POST chat/completions` with model `gpt-4o-mini`, `messages=[{role: user, content: ping}]`, `max_tokens=1`
- `aihub` probe: same payload but against the AI Hub base URL configured in `ai_steps`
- `zsend` probe: `GET https://api.zeabur.com/api/v1/zsend/usage` (no email send)

If the probe returns success, the handler SHALL atomically transition the provider's row to `state='closed'`, `last_probe_at=NOW()`, `last_probe_result='success'`, and update affected `task_failure_log` rows in the open window's range with `recovered_at=NOW()`. The handler SHALL then send a ZSend recovery notification email containing: provider_id, opened_at, closed_at, total paused_task_count, downtime duration in Asia/Taipei.

If the probe fails, `last_probe_at=NOW()`, `last_probe_result='failure'`; state remains `open`; no email sent (avoid spam).

#### Scenario: Successful probe closes circuit

- **GIVEN** `service_circuit_state.openai.state='open'` for 90 minutes
- **WHEN** the circuit-probe beat task runs and the OpenAI ping returns HTTP 200
- **THEN** `service_circuit_state.openai` SHALL be UPDATEd to `state='closed'`, `last_probe_result='success'`
- **AND** exactly one ZSend recovery email SHALL be sent

#### Scenario: Failed probe maintains open state

- **GIVEN** `service_circuit_state.openai.state='open'`
- **WHEN** the circuit-probe beat task runs and the OpenAI ping fails with HTTP 401 (still no key)
- **THEN** `state` SHALL remain `open`
- **AND** `last_probe_result='failure'`
- **AND** no email SHALL be sent

#### Scenario: Closed providers not probed

- **GIVEN** `service_circuit_state.openai.state='closed'`
- **WHEN** the circuit-probe beat task runs
- **THEN** no probe call SHALL be made for `openai`

---

### Requirement: Admin endpoints expose circuit state and manual resume

The backend SHALL expose two admin-only REST endpoints (require admin role + CSRF):

- `GET /admin/service-status` returns JSON `[{provider_id, task_type, state, opened_at, paused_task_count, last_probe_at, last_probe_result, manual_resumed_by, manual_resumed_at}, ...]` for all rows in `service_circuit_state`, sorted by provider_id. Times in ISO 8601 UTC (frontend displays as Asia/Taipei).
- `POST /admin/service-status/{provider_id}/resume` body `{}`. Atomically updates the provider's row to `state='closed'`, `manual_resumed_by=<current admin email>`, `manual_resumed_at=NOW()`, using `UPDATE ... WHERE state='open' RETURNING ...`. If row was already `closed`, returns 409 Conflict. On success, marks affected `task_failure_log` rows `recovered_at=NOW()` and returns 200 with the updated row JSON.

#### Scenario: GET service-status returns all 3 providers

- **WHEN** admin calls `GET /admin/service-status`
- **THEN** the response SHALL be a 200 JSON array of length 3 (openai / aihub / zsend)

#### Scenario: POST resume successfully closes open circuit

- **GIVEN** `service_circuit_state.openai.state='open'`
- **WHEN** admin user `ssweetcoww@gmail.com` calls `POST /admin/service-status/openai/resume`
- **THEN** the response SHALL be 200 with the updated row
- **AND** the row SHALL have `state='closed'`, `manual_resumed_by='ssweetcoww@gmail.com'`, `manual_resumed_at=NOW()`

#### Scenario: POST resume on already-closed circuit returns 409

- **GIVEN** `service_circuit_state.openai.state='closed'`
- **WHEN** admin calls `POST /admin/service-status/openai/resume`
- **THEN** the response SHALL be 409 Conflict
- **AND** the row SHALL remain unchanged

#### Scenario: Non-admin user gets 403

- **WHEN** a non-admin authenticated user calls `POST /admin/service-status/openai/resume`
- **THEN** the response SHALL be 403 Forbidden

---

### Requirement: Admin UI shows service status with manual resume button

The admin frontend SHALL add a new tab "服務狀態" (Service Status) at route `page='admin-service-status'`, accessible from the admin sidebar nav. The tab SHALL render a table with columns: 供應商 (provider_id) / 狀態 (state badge: closed=綠 / open=紅) / 暫停起時 (opened_at in Asia/Taipei, blank if closed) / 影響 task 數 (paused_task_count) / 最後探測 (last_probe_at + result) / 操作 (button).

The 操作 column SHALL show a `[⏵ 手動恢復]` button when `state='open'`, disabled when `state='closed'`. Clicking the button SHALL:

1. Show a confirmation modal: "確定要手動恢復 <provider_id> 服務嗎？影響 <paused_task_count> 個任務會重新加入 queue。"
2. On confirm, POST to `/admin/service-status/{provider_id}/resume`.
3. On 200, refresh the table and show success toast in 繁中 + 台北時間.
4. On 409, show "服務已是正常狀態" toast.

#### Scenario: Open circuit row shows red badge and active button

- **GIVEN** the table includes `{provider_id: 'openai', state: 'open', paused_task_count: 42, opened_at: '...'}`
- **WHEN** admin views the page
- **THEN** the openai row SHALL display a red badge labelled `open`
- **AND** the 操作 column SHALL contain an enabled `手動恢復` button

#### Scenario: Closed circuit row shows green badge and disabled button

- **GIVEN** the table includes `{provider_id: 'aihub', state: 'closed'}`
- **WHEN** admin views the page
- **THEN** the aihub row SHALL display a green badge labelled `closed`
- **AND** the 操作 column SHALL contain a disabled `手動恢復` button (grayed out, no hover)

#### Scenario: Manual resume confirmation flow

- **GIVEN** the open openai row with `paused_task_count=42`
- **WHEN** admin clicks the resume button
- **THEN** a confirmation modal SHALL appear with text "確定要手動恢復 openai 服務嗎？影響 42 個任務會重新加入 queue。"
- **AND** the API call SHALL only fire after admin confirms

---

### Requirement: Permanent provider error triggers fallback provider attempt

When a Celery task using the `aihub` provider raises an exception classified as `permanent` AND the exception is one of the recoverable-via-fallback patterns (`ContentPolicyViolationError`, `budget_exceeded`, `insufficient_quota`), the task SHALL attempt one immediate retry using the OpenAI direct provider as fallback BEFORE writing the failure to `task_failure_log` or triggering the circuit breaker. The fallback path SHALL:

1. Read the OpenAI direct fallback configuration from `ai_steps_fallback` (a new column or related table; baseline: hardcoded `https://api.openai.com/v1` + `OPENAI_API_KEY` env + same model name resolved against an allow-list).
2. Re-issue the same request payload (messages / model / response_format) against the fallback endpoint.
3. If fallback succeeds → record `task_failure_log` with `failure_type='transient'`, `error_message='aihub <error>; recovered via fallback'`, `recovered_at=NOW()`. Task returns success normally; circuit breaker SHALL NOT be triggered for this failure.
4. If fallback also fails → record TWO `task_failure_log` rows (one for aihub permanent error, one for fallback failure). Both count toward circuit breaker thresholds for their respective providers.

Fallback SHALL NOT loop further (no aihub→openai→aihub→...). The fallback SHALL only fire for `aihub` provider failures; `openai` direct provider failures have no fallback and follow the standard permanent-error path.

The fallback model name SHALL be looked up via a hardcoded mapping (e.g. `gemini-2.5-flash-lite` on aihub → `gpt-4o-mini` on openai direct) defined in `app/services/circuit_breaker.py`. If no mapping exists, fallback SHALL be skipped and the task SHALL go to the standard permanent-error path.

#### Scenario: ContentPolicyViolation triggers fallback to OpenAI direct

- **GIVEN** a `classify_episode_topics` task issues a chat call to aihub (model `gemini-2.5-flash-lite`)
- **AND** aihub returns HTTP 400 with `ContentPolicyViolationError`
- **WHEN** the task error handler runs
- **THEN** the task SHALL re-issue the same request to `https://api.openai.com/v1/chat/completions` using `gpt-4o-mini` model
- **AND** if the OpenAI call returns 200, the task SHALL return success
- **AND** `task_failure_log` SHALL contain one row with `failure_type='transient'`, `provider_id='aihub'`, `recovered_at=NOW()`
- **AND** `service_circuit_state.aihub` SHALL remain `closed`

#### Scenario: Budget exceeded triggers fallback to OpenAI direct

- **GIVEN** a `classify_episode_topics` task issues a chat call to aihub
- **AND** aihub returns HTTP 400 with body containing `ExceededBudget`
- **WHEN** the task error handler runs
- **THEN** the task SHALL re-issue the same request to OpenAI direct
- **AND** if successful, the task SHALL return success without opening the aihub circuit

#### Scenario: Both providers fail records two failure rows and may open both circuits

- **GIVEN** a task fails on aihub with `ContentPolicyViolationError`
- **AND** the OpenAI direct fallback also fails with HTTP 401 (invalid_api_key)
- **WHEN** the task error handler completes
- **THEN** `task_failure_log` SHALL contain two rows: one for `provider_id='aihub'` and one for `provider_id='openai'`
- **AND** both providers' circuit breaker thresholds SHALL count these failures toward open transition

#### Scenario: OpenAI direct provider failure does not fallback

- **GIVEN** a task is configured to use `openai` provider directly (not aihub)
- **AND** the call fails with HTTP 401 (permanent)
- **WHEN** the task error handler runs
- **THEN** the task SHALL NOT attempt any fallback
- **AND** one `task_failure_log` row SHALL be written with `failure_type='permanent'`, `provider_id='openai'`
- **AND** the openai circuit breaker SHALL count this toward its threshold

#### Scenario: Unknown model name skips fallback

- **GIVEN** a task on aihub uses a model `claude-haiku-4-5` for which no `aihub→openai` mapping is defined
- **AND** the call fails with `ContentPolicyViolationError`
- **WHEN** the task error handler runs
- **THEN** no fallback SHALL be attempted
- **AND** the failure SHALL go through the standard permanent-error + circuit breaker path

##### Example: aihub-to-openai model mapping

| AI Hub model | OpenAI direct fallback |
| ------------ | ---------------------- |
| `gpt-5-mini` | `gpt-4o-mini` |
| `gemini-2.5-flash-lite` | `gpt-4o-mini` |
| `gpt-4o-mini` | `gpt-4o-mini` |
| `gpt-4o` | `gpt-4o` |
| `claude-haiku-4-5-20251001` | (no fallback) |
