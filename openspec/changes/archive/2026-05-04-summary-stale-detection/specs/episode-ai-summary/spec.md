## MODIFIED Requirements

### Requirement: Episodes table stores AI summary state

The `episodes` table SHALL include six columns related to AI-generated summaries: `ai_summary` (TEXT, nullable), `ai_summary_status` (enum with values `pending` / `running` / `done` / `failed`, NOT NULL, default `pending`), `ai_summary_generated_at` (TIMESTAMP WITH TIME ZONE, nullable), `ai_summary_model` (VARCHAR(100), nullable), `ai_summary_started_at` (TIMESTAMP WITH TIME ZONE, nullable), `ai_summary_error` (TEXT, nullable). The initial migration (already shipped) added the first four; this change SHALL add `ai_summary_started_at` and `ai_summary_error`. The follow-up migration SHALL backfill `ai_summary_started_at = now()` for any pre-existing row whose `ai_summary_status='running'` (so they are not immediately treated as stale by the next cron tick), SHALL leave `ai_summary_started_at IS NULL` on all other rows, SHALL leave `ai_summary_error IS NULL` on all rows, and SHALL NOT enqueue any background work.

#### Scenario: Migration sets pending on existing rows

- **GIVEN** the `episodes` table contains 657 rows before the original ai_summary migration
- **WHEN** that migration adds the original four ai_summary columns
- **THEN** all 657 rows SHALL have `ai_summary_status='pending'`, `ai_summary IS NULL`, `ai_summary_generated_at IS NULL`, `ai_summary_model IS NULL`
- **AND** no Celery task SHALL be enqueued as part of the migration

#### Scenario: New episode row defaults to pending

- **WHEN** a new row is INSERTed into `episodes` (e.g. via RSS sync)
- **THEN** the new row SHALL have `ai_summary_status='pending'` by default
- **AND** the new row SHALL have `ai_summary_started_at IS NULL` and `ai_summary_error IS NULL`

#### Scenario: Stale-detection migration preserves currently running rows

- **GIVEN** before the new migration, the `episodes` table contains 3 rows with `ai_summary_status='running'` and 200 rows with `ai_summary_status='done'`
- **WHEN** the migration that adds `ai_summary_started_at` and `ai_summary_error` runs
- **THEN** the 3 running rows SHALL have `ai_summary_started_at = now()` (the migration timestamp) and `ai_summary_error IS NULL`
- **AND** the 200 done rows SHALL have `ai_summary_started_at IS NULL` and `ai_summary_error IS NULL`

### Requirement: Map-reduce summary task with retries

The Celery task `generate_episode_summary(episode_id)` SHALL produce an 80-150-character Traditional Chinese summary using a two-stage map-reduce pipeline backed by the LLM endpoint configured at `ai_steps.summary` (resolved via `services.ai_step_resolver.get_step_config('summary')`).

Stage 1 (map): the task SHALL split the episode's transcript into chunks of at most 12,000 tokens (counted with `tiktoken` `cl100k_base` encoding), aligned to `transcript_segments` boundaries (chunks SHALL NOT split a segment). For each chunk, the task SHALL call the LLM with a prompt asking for 3-5 bullet-point key takeaways in Traditional Chinese.

Stage 2 (reduce): the task SHALL concatenate all chunk takeaways and call the LLM once more with a prompt asking for an 80-150-character Traditional Chinese summary.

The task SHALL use Celery `autoretry_for` covering transient errors (network errors, rate limits, server 5xx) with `max_retries=3` and exponential backoff. After 3 retries, the task SHALL set `ai_summary_status='failed'`, `ai_summary_generated_at=now()`, and `ai_summary_error` to a short string describing the final exception (truncated to at most 1000 characters). On success it SHALL set `ai_summary` to the reduced text, `ai_summary_status='done'`, `ai_summary_generated_at=now()`, `ai_summary_model` to the model name resolved from `ai_steps.summary`, and SHALL clear `ai_summary_error` to NULL.

When the task transitions an episode from `pending` (or `failed`) to `running`, it SHALL set `ai_summary_started_at = now()` in the same UPDATE that writes the new status. The task SHALL register a Celery `on_failure` handler that runs even when the worker is killed by an unhandled exception escaping the autoretry policy: the handler SHALL set `ai_summary_status='failed'`, `ai_summary_generated_at=now()`, and `ai_summary_error` to the exception's `repr()` (truncated to at most 1000 characters), but SHALL NOT overwrite a row whose `ai_summary_status` is already `done`.

#### Scenario: Single 30-minute episode produces a done summary

- **GIVEN** an episode with a transcript whose total token count is 24,000 (≈30 min)
- **AND** `ai_steps.summary` is configured with a working endpoint and api_key
- **WHEN** `generate_episode_summary(episode_id)` runs to completion
- **THEN** the LLM SHALL be called twice for stage 1 (2 chunks of 12K each) and once for stage 2
- **AND** the row SHALL end with `ai_summary_status='done'`, `ai_summary` non-null, `ai_summary_generated_at` and `ai_summary_model` populated, `ai_summary_error IS NULL`

##### Example: chunk count by transcript length

| Transcript tokens | Stage 1 chunks | Total LLM calls |
|-------------------|----------------|-----------------|
| 8,000 | 1 | 2 |
| 24,000 | 2 | 3 |
| 36,000 | 3 | 4 |
| 60,000 | 5 | 6 |

#### Scenario: Failed task after 3 retries marks status failed

- **GIVEN** the LLM endpoint is unreachable (returns 5xx repeatedly)
- **WHEN** `generate_episode_summary(episode_id)` is called and exhausts 3 retries
- **THEN** `ai_summary_status` SHALL be `failed`, `ai_summary_generated_at` SHALL be set to the time of the final attempt, `ai_summary` SHALL remain NULL
- **AND** `ai_summary_error` SHALL be a non-empty string of at most 1000 characters describing the final HTTP 5xx exception

#### Scenario: Idempotent short-circuit when status is done

- **GIVEN** an episode row with `ai_summary_status='done'` and `ai_summary='...existing summary...'`
- **WHEN** `generate_episode_summary(episode_id)` is invoked again
- **THEN** the task SHALL log an info message and return without calling the LLM, and the row SHALL be unchanged

#### Scenario: Skip when status is running

- **GIVEN** an episode row with `ai_summary_status='running'`
- **WHEN** another `generate_episode_summary(episode_id)` invocation enters the task
- **THEN** the task SHALL log a warning and return early without calling the LLM and without modifying the row

#### Scenario: Resolver missing throws explicit error before LLM call

- **GIVEN** `ai_steps.summary` row exists but `api_key_id IS NULL`
- **WHEN** `generate_episode_summary(episode_id)` runs
- **THEN** the task SHALL raise `AiStepNotConfiguredError` synchronously (before any LLM HTTP call), Celery SHALL retry per the autoretry policy and ultimately mark the task `failed` after 3 retries (since the misconfiguration persists)
- **AND** `ai_summary_error` SHALL contain the string `AiStepNotConfiguredError`

#### Scenario: Task entry sets started_at when transitioning to running

- **GIVEN** an episode row with `ai_summary_status='pending'` and `ai_summary_started_at IS NULL`
- **WHEN** `generate_episode_summary(episode_id)` enters the task body and updates `ai_summary_status='running'`
- **THEN** the same UPDATE statement SHALL set `ai_summary_started_at = now()`
- **AND** if the row is later transitioned to `done` or `failed`, `ai_summary_started_at` SHALL remain set to that started time (it SHALL NOT be cleared)

#### Scenario: on_failure handler marks failed when worker is killed mid-task

- **GIVEN** an episode row with `ai_summary_status='running'` and `ai_summary_started_at = now() - 30s`
- **AND** the worker process is killed with SIGKILL (OOM, container restart) while executing the task body, after the autoretry policy has been bypassed by an exception that does not match `autoretry_for`
- **WHEN** the Celery `on_failure` callback fires
- **THEN** the row SHALL have `ai_summary_status='failed'`, `ai_summary_generated_at = now()`, `ai_summary_error` set to a non-empty string describing the exception (at most 1000 characters)
- **AND** if the row had already been transitioned to `done` by an earlier successful attempt, the `on_failure` handler SHALL NOT modify the row

## ADDED Requirements

### Requirement: Cron tick recovers stale-running summary rows

A periodic task SHALL detect summary rows whose status has been `running` for longer than `summary_stale_threshold_seconds` (config setting, default 600 seconds, overridable via env `SUMMARY_STALE_THRESHOLD_SECONDS`) and recover them by resetting status to `pending`, clearing `ai_summary_started_at` to NULL, writing a short reason into `ai_summary_error` (e.g. `"recovered from stale running after 612s"`), and re-enqueueing `generate_episode_summary.delay(episode_id)`. Recovery SHALL be idempotent: a single tick SHALL recover at most all currently-stale rows in one batch, and SHALL log the count of rows recovered (or zero, silently). Recovery SHALL NOT touch rows whose `ai_summary_started_at IS NULL` (defensive: these rows have inconsistent state and SHALL be inspected manually rather than auto-recovered).

#### Scenario: Stale row is reset and re-enqueued

- **GIVEN** an episode row with `ai_summary_status='running'` and `ai_summary_started_at = now() - 700s`
- **AND** `summary_stale_threshold_seconds = 600`
- **WHEN** the cron tick runs
- **THEN** the row SHALL be UPDATEd to `ai_summary_status='pending'`, `ai_summary_started_at IS NULL`, `ai_summary_error = 'recovered from stale running after 700s'`
- **AND** `generate_episode_summary.delay(episode_id)` SHALL be enqueued exactly once for this row

#### Scenario: Fresh running row is left alone

- **GIVEN** an episode row with `ai_summary_status='running'` and `ai_summary_started_at = now() - 60s`
- **AND** `summary_stale_threshold_seconds = 600`
- **WHEN** the cron tick runs
- **THEN** the row SHALL NOT be modified and no Celery task SHALL be enqueued for it

#### Scenario: Running row with NULL started_at is skipped

- **GIVEN** an episode row with `ai_summary_status='running'` and `ai_summary_started_at IS NULL`
- **WHEN** the cron tick runs
- **THEN** the row SHALL NOT be modified and no Celery task SHALL be enqueued for it
- **AND** the cron tick SHALL log a warning naming the row id so an operator can investigate

#### Scenario: Cron tick errors do not break unrelated tick work

- **GIVEN** the stale-summary helper raises an unexpected database error mid-tick
- **WHEN** the cron tick runs
- **THEN** the error SHALL be caught and logged, and the rest of the tick (transcription stale detection, schedule refreshes) SHALL continue running

### Requirement: Admin queue response exposes summary error message

The admin queue endpoint (`GET /admin/queue`) SHALL include `ai_summary_error` (string or null) for each item in `pending` / `running` / `completed`, alongside the existing `ai_summary_status`. The frontend `SummaryBadge` in `src/AdminPage.jsx` Queue Tab SHALL render the error string in a hover tooltip when `ai_summary_status='failed'` and `ai_summary_error` is non-null. When `ai_summary_error IS NULL` (e.g. failed before this change shipped), the badge SHALL fall back to a generic tooltip such as `"Summary task failed (no error message recorded)"`.

#### Scenario: Failed item exposes error in API and tooltip

- **GIVEN** an episode with `ai_summary_status='failed'` and `ai_summary_error='openai.APIError: rate limited'`
- **WHEN** an admin loads the queue tab and hovers the failed badge
- **THEN** `GET /admin/queue` SHALL return the item with `ai_summary_error='openai.APIError: rate limited'`
- **AND** the badge tooltip SHALL display `'openai.APIError: rate limited'` (truncated in the UI if longer than 200 chars)

#### Scenario: Legacy failed item without error string falls back

- **GIVEN** an episode that was marked `failed` before this change shipped, so `ai_summary_error IS NULL`
- **WHEN** an admin loads the queue tab
- **THEN** the badge tooltip SHALL display the fallback string `"Summary task failed (no error message recorded)"`
