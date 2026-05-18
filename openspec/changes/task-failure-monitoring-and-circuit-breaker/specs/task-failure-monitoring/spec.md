## ADDED Requirements

### Requirement: Persisted task failure log

The backend SHALL maintain a `task_failure_log` table that records every Celery task failure with the following columns: `id` (UUID PK), `task_name` (string), `task_args_json` (jsonb), `failure_type` (enum: `permanent` | `transient` | `unknown`), `error_class` (string), `error_message` (text, truncated to 4KB), `provider_id` (nullable string: `openai` | `aihub` | `zsend`), `retry_count` (int), `failed_at` (timestamptz), `alerted_at` (nullable timestamptz), `recovered_at` (nullable timestamptz). Each Celery task SHALL register a `Task.on_failure` handler that writes one row to this table on every final failure (after retry exhaustion or for permanent errors immediately).

#### Scenario: Permanent error writes one row immediately

- **GIVEN** a `transcribe_episode` task hits an `InvalidApiKeyError` (HTTP 401) classified as permanent
- **WHEN** the task fails
- **THEN** exactly one row SHALL be inserted into `task_failure_log` with `failure_type='permanent'`, `provider_id='openai'`, `retry_count=0`, `failed_at=NOW()`

#### Scenario: Transient error writes one row after retries exhausted

- **GIVEN** a `classify_episode_topics` task fails 3 times with `httpx.TimeoutException` (transient)
- **WHEN** Celery exhausts `max_retries=3`
- **THEN** exactly one row SHALL be inserted into `task_failure_log` with `failure_type='transient'`, `retry_count=3`

#### Scenario: Failure log table has retention cleanup

- **GIVEN** `task_failure_log` rows older than 30 days exist
- **WHEN** the daily cleanup beat task runs
- **THEN** rows with `failed_at < NOW() - INTERVAL '30 days'` SHALL be deleted

---

### Requirement: Error classifier categorises exceptions as permanent or transient

The backend SHALL provide a service `app.services.error_classifier` exposing `classify(exc) -> Literal['permanent', 'transient', 'unknown']`. The classifier SHALL recognise as `permanent`:

- HTTP responses with status 401, 402, 403, 415, 422
- HTTP 400 responses whose body contains any of: `context_length_exceeded`, `invalid_api_key`, `insufficient_quota`
- Celery exceptions: `celery.exceptions.NotRegistered`, `kombu.exceptions.MessageStateError`
- Custom exceptions: `app.services.exceptions.InvalidProviderConfigError`, `app.services.exceptions.PromptTooLongError`

All other exceptions SHALL be classified as `transient`. If classification cannot proceed (unexpected exception structure), the result SHALL be `unknown` and SHALL be treated as `transient` for retry purposes.

#### Scenario: HTTP 402 classified permanent

- **WHEN** `classify(httpx.HTTPStatusError(response=Response(status_code=402)))` is called
- **THEN** the return value SHALL be `'permanent'`

#### Scenario: HTTP 429 rate limit classified transient

- **WHEN** `classify(httpx.HTTPStatusError(response=Response(status_code=429)))` is called
- **THEN** the return value SHALL be `'transient'`

#### Scenario: Network timeout classified transient

- **WHEN** `classify(httpx.TimeoutException("read timeout"))` is called
- **THEN** the return value SHALL be `'transient'`

#### Scenario: TaskNotRegistered classified permanent

- **WHEN** `classify(celery.exceptions.NotRegistered("app.workers.foo"))` is called
- **THEN** the return value SHALL be `'permanent'`

##### Example: classification table

| Exception | Result |
| --------- | ------ |
| `HTTPStatusError(401)` | permanent |
| `HTTPStatusError(402)` | permanent |
| `HTTPStatusError(415)` | permanent |
| `HTTPStatusError(400, body="context_length_exceeded")` | permanent |
| `HTTPStatusError(400, body="bad request")` | transient |
| `HTTPStatusError(429)` | transient |
| `HTTPStatusError(503)` | transient |
| `httpx.TimeoutException` | transient |
| `celery.exceptions.NotRegistered` | permanent |
| `KeyError("missing")` | unknown (treated as transient) |

---

### Requirement: Permanent errors short-circuit Celery retry

When a Celery task raises an exception that the error classifier returns as `permanent`, the task SHALL NOT use Celery's `autoretry_for` retry path. Instead the task's exception handler SHALL:

1. Call `error_classifier.classify(exc)` first.
2. If permanent → write a `task_failure_log` row with `failure_type='permanent'`, `retry_count=<current task.request.retries>`, then re-raise WITHOUT calling `self.retry(...)`.
3. If transient or unknown → fall through to existing `autoretry_for` behaviour (Celery handles retry).

The `tasks.py` / `topic_task.py` / `summary_task.py` task definitions SHALL implement this short-circuit. Other tasks (quota_digest / eval_reminder / db_backup) MAY adopt it as appropriate but SHALL at minimum write to `task_failure_log` on final failure.

#### Scenario: Permanent error skips retry

- **GIVEN** a `transcribe_episode` task with `task.request.retries == 0`
- **WHEN** the task raises `HTTPStatusError(402)` (permanent)
- **THEN** Celery SHALL NOT retry the task
- **AND** one row SHALL be written to `task_failure_log` with `retry_count=0`
- **AND** the task's status in Celery result backend SHALL be `FAILURE`

#### Scenario: Transient error follows existing retry path

- **GIVEN** a `transcribe_episode` task with `task.request.retries == 0`
- **WHEN** the task raises `httpx.TimeoutException`
- **THEN** Celery SHALL retry the task per existing `autoretry_for` config
- **AND** no row SHALL be written to `task_failure_log` until retries are exhausted

---

### Requirement: Sliding-window failure rate alert

The backend SHALL register a Celery Beat schedule entry `failure-alert` running every 5 minutes (cron `*/5 * * * *`). The handler SHALL:

1. SELECT each `task_name` having `COUNT(*) >= 3` rows in `task_failure_log` where `failed_at > NOW() - INTERVAL '30 minutes'` AND `alerted_at IS NULL`.
2. For each such `task_name`, send a ZSend email to `settings.zsend_admin_to_email` containing: task name, failure count in window, last 3 error_messages (truncated to 200 chars each), failed_at timestamps in Asia/Taipei timezone, count grouped by provider_id.
3. Update `alerted_at = NOW()` for the rows included in the alert (so they are not re-alerted).

If the ZSend send call fails (transient), the rows SHALL NOT be marked alerted; the next 5-min tick will retry. If ZSend is not configured (`settings.zsend_api_key is None`), the handler SHALL log "ZSend not configured, skipping alert" and SHALL NOT mark rows alerted.

#### Scenario: 3 failures in 30 minutes triggers email

- **GIVEN** `task_failure_log` has 3 rows for `transcribe_episode` with `failed_at` within the last 30 minutes and `alerted_at IS NULL`
- **WHEN** the failure-alert beat task runs
- **THEN** exactly one ZSend email SHALL be sent
- **AND** the 3 rows SHALL have `alerted_at = NOW()`

#### Scenario: 2 failures does not trigger

- **GIVEN** `task_failure_log` has 2 rows for `transcribe_episode` within 30 minutes
- **WHEN** the failure-alert beat task runs
- **THEN** no email SHALL be sent
- **AND** the 2 rows SHALL retain `alerted_at IS NULL`

#### Scenario: Already-alerted rows not re-alerted

- **GIVEN** 3 rows for `transcribe_episode` already have `alerted_at = NOW() - 10 minutes`
- **WHEN** the failure-alert beat task runs
- **THEN** no email SHALL be sent

#### Scenario: ZSend send failure leaves rows un-alerted for retry

- **GIVEN** 3 qualifying rows exist and the ZSend HTTP call raises `httpx.TimeoutException`
- **WHEN** the failure-alert beat task runs
- **THEN** the 3 rows SHALL retain `alerted_at IS NULL`
- **AND** the next failure-alert tick SHALL re-attempt the email

#### Scenario: ZSend not configured logs and skips

- **GIVEN** `settings.zsend_api_key is None` and 3 qualifying rows exist
- **WHEN** the failure-alert beat task runs
- **THEN** the handler SHALL log a warning "ZSend not configured, skipping alert"
- **AND** the 3 rows SHALL retain `alerted_at IS NULL`
- **AND** no email SHALL be sent
