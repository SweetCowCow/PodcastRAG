## ADDED Requirements

### Requirement: Episodes table stores AI summary state

The `episodes` table SHALL include four columns related to AI-generated summaries: `ai_summary` (TEXT, nullable), `ai_summary_status` (enum with values `pending` / `running` / `done` / `failed`, NOT NULL, default `pending`), `ai_summary_generated_at` (TIMESTAMP WITH TIME ZONE, nullable), `ai_summary_model` (VARCHAR(100), nullable). The migration that adds these columns SHALL set `ai_summary_status='pending'` for all pre-existing rows and SHALL NOT enqueue any background work.

#### Scenario: Migration sets pending on existing rows

- **GIVEN** the `episodes` table contains 657 rows before the migration
- **WHEN** the migration adds the four ai_summary columns
- **THEN** all 657 rows SHALL have `ai_summary_status='pending'`, `ai_summary IS NULL`, `ai_summary_generated_at IS NULL`, `ai_summary_model IS NULL`
- **AND** no Celery task SHALL be enqueued as part of the migration

#### Scenario: New episode row defaults to pending

- **WHEN** a new row is INSERTed into `episodes` (e.g. via RSS sync)
- **THEN** the new row SHALL have `ai_summary_status='pending'` by default

---

### Requirement: Map-reduce summary task with retries

The Celery task `generate_episode_summary(episode_id)` SHALL produce an 80-150-character Traditional Chinese summary using a two-stage map-reduce pipeline backed by the LLM endpoint configured at `ai_steps.summary` (resolved via `services.ai_step_resolver.get_step_config('summary')`).

Stage 1 (map): the task SHALL split the episode's transcript into chunks of at most 12,000 tokens (counted with `tiktoken` `cl100k_base` encoding), aligned to `transcript_segments` boundaries (chunks SHALL NOT split a segment). For each chunk, the task SHALL call the LLM with a prompt asking for 3-5 bullet-point key takeaways in Traditional Chinese.

Stage 2 (reduce): the task SHALL concatenate all chunk takeaways and call the LLM once more with a prompt asking for an 80-150-character Traditional Chinese summary.

The task SHALL use Celery `autoretry_for` covering transient errors (network errors, rate limits, server 5xx) with `max_retries=3` and exponential backoff. After 3 retries, the task SHALL set `ai_summary_status='failed'` and `ai_summary_generated_at=now()`. On success it SHALL set `ai_summary` to the reduced text, `ai_summary_status='done'`, `ai_summary_generated_at=now()`, `ai_summary_model` to the model name resolved from `ai_steps.summary`.

#### Scenario: Single 30-minute episode produces a done summary

- **GIVEN** an episode with a transcript whose total token count is 24,000 (≈30 min)
- **AND** `ai_steps.summary` is configured with a working endpoint and api_key
- **WHEN** `generate_episode_summary(episode_id)` runs to completion
- **THEN** the LLM SHALL be called twice for stage 1 (2 chunks of 12K each) and once for stage 2
- **AND** the row SHALL end with `ai_summary_status='done'`, `ai_summary` non-null, `ai_summary_generated_at` and `ai_summary_model` populated

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

---

### Requirement: Pipeline chains summary task after transcription completion

The transcription worker SHALL enqueue `generate_episode_summary.delay(episode_id)` immediately after writing `transcription_queue.status='completed'` in `_mark_queue_finished()`. A failure of `generate_episode_summary` SHALL NOT modify `transcription_queue.status`, `started_at`, `finished_at`, or `error_message`.

#### Scenario: Transcription success enqueues summary

- **WHEN** `_mark_queue_finished(episode_id, status=completed)` returns
- **THEN** a Celery task `generate_episode_summary` SHALL have been enqueued with the same `episode_id`

#### Scenario: Summary failure does not retroactively fail transcription

- **GIVEN** a transcription completed successfully and `transcription_queue.status='completed'`
- **WHEN** `generate_episode_summary` for that episode exhausts retries and sets `ai_summary_status='failed'`
- **THEN** `transcription_queue.status` SHALL remain `completed` and `transcription_queue.error_message` SHALL remain NULL

---

### Requirement: Admin endpoints for regenerate and backfill

The backend SHALL expose two admin-only endpoints:

1. `POST /admin/episodes/{episode_id}/regenerate-summary`: SHALL UPDATE the episode's `ai_summary_status='pending'` (regardless of current value) and enqueue `generate_episode_summary.delay(episode_id)`. SHALL return `200 {episode_id, enqueued: true}`. If the episode does not exist, return `404`.

2. `POST /admin/episodes/backfill-summary`: SHALL SELECT all episode rows where `ai_summary IS NULL AND transcript_status='completed'`, enqueue `generate_episode_summary.delay(episode_id)` for each, and return `200 {enqueued_count: N}`. The endpoint SHALL be idempotent: calling it twice SHALL NOT cause data corruption. The endpoint SHALL NOT pass any throttle / batch_size parameter; concurrency is governed by Celery worker concurrency.

#### Scenario: Regenerate sets row back to pending and enqueues

- **GIVEN** an episode with `ai_summary_status='failed'`
- **WHEN** an admin POSTs `/admin/episodes/{episode_id}/regenerate-summary`
- **THEN** the row's `ai_summary_status` SHALL be `pending` immediately after the request returns
- **AND** a Celery task `generate_episode_summary` for this `episode_id` SHALL be enqueued

#### Scenario: Backfill returns enqueued count

- **GIVEN** 100 episodes with `transcript_status='completed' AND ai_summary IS NULL`
- **AND** 200 other episodes already have `ai_summary` filled
- **WHEN** an admin POSTs `/admin/episodes/backfill-summary`
- **THEN** the response SHALL be `{enqueued_count: 100}`
- **AND** 100 Celery tasks SHALL have been enqueued

#### Scenario: Regenerate not authorized for non-admin

- **WHEN** a non-admin user POSTs `/admin/episodes/{episode_id}/regenerate-summary`
- **THEN** the backend SHALL return `403 Forbidden` (or `401` if unauthenticated) and SHALL NOT modify the row

---

### Requirement: User-facing display falls back to RSS description

The frontend SHALL display, on `PodcastSelect`, `QueryPage` episode panel, and `TranscriptPage`, the following text under each episode:

- If `ai_summary_status === 'done' AND ai_summary != null AND ai_summary != ''`: display `ai_summary`.
- Otherwise: display `episode.description` (the original RSS description). If `episode.description` is also null/empty, display nothing (no element rendered).

The frontend SHALL NOT display loading spinners, "summary in progress" text, "summary failed" text, or any indication of internal AI summary state to end users in any of the three views above.

#### Scenario: Display ai_summary when done

- **GIVEN** episode with `ai_summary_status='done'` and `ai_summary='重點：...'`
- **WHEN** the user views `PodcastSelect`
- **THEN** the episode card SHALL show `重點：...` text

#### Scenario: Display fallback when status is pending

- **GIVEN** episode with `ai_summary_status='pending'`, `ai_summary IS NULL`, `description='RSS 原描述'`
- **WHEN** the user views `QueryPage` episode panel
- **THEN** the panel SHALL show `RSS 原描述` and SHALL NOT show any spinner or "AI 摘要產生中" text

#### Scenario: Display fallback when status is failed

- **GIVEN** episode with `ai_summary_status='failed'`, `ai_summary IS NULL`, `description='RSS 原描述'`
- **WHEN** the user views `TranscriptPage`
- **THEN** the page SHALL show `RSS 原描述` and SHALL NOT show any "失敗" / "failed" text

#### Scenario: Display nothing when both ai_summary and description are absent

- **GIVEN** episode with `ai_summary IS NULL` and `description IS NULL`
- **WHEN** the user views any of the three pages
- **THEN** the section SHALL be omitted (empty string), and SHALL NOT render an empty box / placeholder

---

### Requirement: Admin queue tab shows summary badge and controls

The admin `Transcription Queue` tab (`AdminPage.jsx` QueueTab) SHALL display an additional summary badge for each episode row whose `transcript_status='completed'`. The badge SHALL render one of three labels (zh-tw / en):

- `pending` or `running` → `摘要中` / `Summarising`
- `done` → `已摘要` / `Summarised`
- `failed` → `摘要失敗` / `Summary failed`

For rows whose `transcript_status != 'completed'`, the summary badge SHALL NOT render.

For rows whose `ai_summary_status='failed'`, the row SHALL show a "重跑" / "Retry" icon button next to the badge that POSTs `/admin/episodes/{id}/regenerate-summary`.

The QueueTab page SHALL display a "批次補摘要" / "Backfill Summaries" button at the top. Clicking it SHALL POST `/admin/episodes/backfill-summary` and SHALL show a toast with the returned `enqueued_count` (e.g. `已排入 N 集` / `Queued N episodes`).

#### Scenario: Summary badge text by status

- **GIVEN** four episode rows with `transcript_status='completed'` and `ai_summary_status` values `pending`, `running`, `done`, `failed`
- **WHEN** the admin views the QueueTab
- **THEN** the four rows SHALL show `摘要中`, `摘要中`, `已摘要`, `摘要失敗` respectively (zh)

#### Scenario: Summary badge hidden when transcript not completed

- **GIVEN** an episode row with `transcript_status='processing'`, `ai_summary_status='pending'`
- **WHEN** the admin views the QueueTab
- **THEN** only the transcript badge SHALL render; no summary badge SHALL appear next to it

#### Scenario: Retry button on failed row

- **GIVEN** an episode row with `ai_summary_status='failed'`
- **WHEN** the admin clicks the row's retry icon
- **THEN** a `POST /admin/episodes/{id}/regenerate-summary` request SHALL be issued
- **AND** on success, the badge SHALL update to `摘要中` (status pending after the response)

#### Scenario: Backfill button toast shows enqueued count

- **GIVEN** the backend has 50 episodes matching backfill criteria
- **WHEN** the admin clicks "批次補摘要" and the response returns `{enqueued_count: 50}`
- **THEN** the UI SHALL show a toast saying `已排入 50 集` (zh) or `Queued 50 episodes` (en)

---

### Requirement: Episode list API includes ai_summary fields

The `GET /shows/{show_id}/episodes` endpoint SHALL include `ai_summary` (string or null) and `ai_summary_status` (one of `pending`, `running`, `done`, `failed`) for each episode in its response. The endpoint SHALL NOT expose `ai_summary_model` to non-admin callers (that field SHALL be admin-API-only).

#### Scenario: Episode list returns ai_summary fields

- **WHEN** a client calls `GET /shows/{show_id}/episodes` and the show has 3 episodes with `ai_summary_status` values `done`, `pending`, `failed`
- **THEN** the response SHALL contain three episode objects, each with `ai_summary` (string or null) and `ai_summary_status` fields populated correctly
- **AND** none of the objects SHALL contain `ai_summary_model`
