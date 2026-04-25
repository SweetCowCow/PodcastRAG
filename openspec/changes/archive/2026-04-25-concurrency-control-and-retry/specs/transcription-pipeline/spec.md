## ADDED Requirements

### Requirement: Transient errors trigger automatic retry with exponential backoff

The `transcribe_episode` Celery task SHALL automatically retry on the following transient exceptions: `httpx.HTTPError`, `httpx.TimeoutException`, `openai.RateLimitError`, `openai.APIConnectionError`, `openai.APITimeoutError`, `asyncio.TimeoutError`, and `ConnectionError`. The task SHALL be configured with `max_retries=3`, `retry_backoff=True`, `retry_backoff_max=300`, and `retry_jitter=True`, producing a retry delay sequence starting near 10 seconds, doubling each attempt, capped at 300 seconds, with random jitter applied.

#### Scenario: OpenAI 429 triggers retry

- **WHEN** the task calls the OpenAI Whisper API and receives a `RateLimitError`
- **THEN** Celery SHALL requeue the task using autoretry with exponential backoff starting around 10 seconds

#### Scenario: httpx timeout triggers retry

- **WHEN** the task encounters `httpx.TimeoutException` while downloading audio from R2
- **THEN** Celery SHALL requeue the task and the attempt counter SHALL advance

#### Scenario: Retry count limits total attempts

- **WHEN** a task has already been retried 3 times via autoretry and encounters another transient error
- **THEN** the task SHALL be marked failed, transcript.status SHALL be set to 'failed', and no further retries SHALL occur

### Requirement: Permanent errors bypass retry and mark transcript failed

The task SHALL classify the following exceptions as permanent and SHALL NOT retry them: `RssParseError`, `StorageError` (R2 fixed errors such as `AccessDenied` or `NoSuchBucket`), `FileNotFoundError`, `pydub.exceptions.CouldntDecodeError`, `openai.AuthenticationError`, and `openai.BadRequestError`. On a permanent error, the task SHALL set `transcript.status='failed'`, write the exception message into `transcript.error_message` (truncated to at most `ERROR_MESSAGE_MAX_LEN` characters), commit the change, release the global slot and per-show lock, and return a failure summary without raising.

#### Scenario: Audio decode failure is not retried

- **WHEN** pydub raises `CouldntDecodeError` while processing an episode's audio
- **THEN** transcript.status SHALL be set to 'failed', error_message SHALL contain the decoder error string, and the task SHALL NOT be retried

#### Scenario: OpenAI authentication error is not retried

- **WHEN** the Whisper API rejects the key with `AuthenticationError`
- **THEN** transcript.status SHALL be set to 'failed' and the task SHALL NOT be retried (retrying with the same invalid key is pointless)

#### Scenario: Permanent error still releases locks

- **WHEN** the task encounters a permanent error after acquiring both the global slot and per-show lock
- **THEN** before returning, the task SHALL decrement `transcribe:global:active_count`, delete `transcribe:global:slot:{task_id}`, and delete `transcribe:show:{show_id}:lock`

### Requirement: MAX_CONCURRENT_TRANSCRIPTIONS is a backend setting

The backend `Settings` class SHALL expose a `max_concurrent_transcriptions: int = 1` field read from the `MAX_CONCURRENT_TRANSCRIPTIONS` environment variable. Both the backend API service (for reporting via queue-status endpoint) and the worker service (for enforcing the semaphore) SHALL read from this setting.

#### Scenario: Default value applied when env var unset

- **WHEN** the backend or worker starts without `MAX_CONCURRENT_TRANSCRIPTIONS` defined
- **THEN** `settings.max_concurrent_transcriptions` SHALL equal 1

#### Scenario: Env var overrides default

- **WHEN** the worker starts with `MAX_CONCURRENT_TRANSCRIPTIONS=3`
- **THEN** `settings.max_concurrent_transcriptions` SHALL equal 3 and the global semaphore SHALL allow up to 3 concurrent tasks
