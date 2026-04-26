# transcription-progress-api Specification

## Purpose

TBD - created by archiving change 'transcription-progress-visibility'. Update Purpose after archive.

## Requirements

### Requirement: Transcription progress aggregate endpoint per show

The backend SHALL expose `GET /shows/{show_id}/transcription-status` that returns a single JSON payload aggregating the transcription state of every episode belonging to the given show, so that the frontend can render per-show progress without per-episode round-trips.

The response payload SHALL have the shape:

```
{
  "counts": {
    "pending": <int>,
    "processing": <int>,
    "completed": <int>,
    "failed": <int>
  },
  "currently_processing": [
    { "episode_id": "<uuid>", "episode_title": "<string>", "started_at": "<ISO-8601 timestamp>" },
    ...
  ],
  "recent_failures": [
    {
      "episode_id": "<uuid>",
      "episode_title": "<string>",
      "error_message": "<string, truncated to 200 characters>",
      "error_category": "quota_exceeded" | "rate_limited" | "auth_error" | "server_error" | "network_error" | "unknown" | null,
      "failed_at": "<ISO-8601 timestamp>"
    },
    ...
  ]
}
```

The endpoint SHALL return `currently_processing` limited to at most 10 episodes ordered by `started_at` ascending (oldest first), and SHALL return `recent_failures` limited to at most 10 episodes ordered by `failed_at` descending (newest first).

The endpoint SHALL derive `started_at` from the most recent transition into `processing` state, using `transcripts.updated_at` as the timestamp. The endpoint SHALL derive `failed_at` likewise using `transcripts.updated_at` on rows whose `status = 'failed'`.

`error_message` SHALL be the DB `transcripts.error_message` value truncated at 200 characters (no ellipsis added by the backend; truncation is pure byte slice in UTF-8 safe manner). `error_category` SHALL be null if no category was recorded at failure time; backend SHALL NOT infer category by re-parsing `error_message`.

The endpoint SHALL return HTTP 404 if no show exists with the given `show_id`.

#### Scenario: Mixed statuses aggregated correctly

- **WHEN** a show has 5 pending, 2 processing, 10 completed, 1 failed episodes
- **THEN** `GET /shows/{id}/transcription-status` SHALL return `counts = {pending: 5, processing: 2, completed: 10, failed: 1}`
- **AND** `currently_processing` SHALL contain exactly 2 entries
- **AND** `recent_failures` SHALL contain exactly 1 entry

#### Scenario: Show with no transcripts

- **WHEN** a show exists but has zero episodes (or zero transcripts)
- **THEN** the endpoint SHALL return `counts = {pending: 0, processing: 0, completed: 0, failed: 0}`, `currently_processing = []`, `recent_failures = []`

#### Scenario: Unknown show

- **WHEN** no show row exists for the requested `show_id`
- **THEN** the endpoint SHALL return HTTP 404 with a JSON body containing a `detail` field

#### Scenario: Error message truncated at 200 characters

- **WHEN** a failed transcript has `error_message` of length 500 characters
- **THEN** the response `recent_failures[i].error_message` SHALL contain exactly the first 200 characters of the stored value
- **AND** the response SHALL NOT include characters beyond position 200

#### Scenario: Ordering stable across calls

- **WHEN** the endpoint is called twice in succession with no DB state change between calls
- **THEN** both responses SHALL return `currently_processing` and `recent_failures` in identical order


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
### Requirement: External API status endpoint for admin

The backend SHALL expose `GET /admin/external-api-status` that returns the most recent health data for each tracked external API, sourced from the `api_health` tracker, so that administrators can see live API health in one place.

The response payload SHALL have the shape:

```
{
  "apis": [
    {
      "name": "openai_whisper" | "openai_chat" | "openai_embedding",
      "latest": {
        "ts_ms": <int>,
        "ok": <bool>,
        "duration_ms": <int>,
        "error_category": <string|null>,
        "http_status": <int|null>
      } | null,
      "recent": [ ... up to 20 events, same shape as latest, ordered newest first ],
      "degraded": <bool>
    },
    ...
  ]
}
```

The endpoint SHALL always return one entry per known API name even when no events have been recorded (in which case `latest` SHALL be null and `recent` SHALL be an empty list). The endpoint SHALL set the per-API `degraded` flag to true when the tracker's `get_recent` call reported a Redis failure for that API and SHALL NOT fail the whole response.

#### Scenario: All APIs healthy

- **WHEN** each of the three APIs has one or more recorded events, all with `ok: true`
- **THEN** the response SHALL contain three entries each with a non-null `latest` whose `ok = true`, a non-empty `recent`, and `degraded = false`

#### Scenario: One API has never been called

- **WHEN** `api_health:openai_embedding` has no entries but the other two APIs do
- **THEN** the embedding entry SHALL have `latest = null`, `recent = []`, `degraded = false`; the other two SHALL have data as recorded

#### Scenario: Redis unreachable

- **WHEN** Redis is unreachable at request time
- **THEN** the endpoint SHALL return HTTP 200 with every API entry's `latest = null`, `recent = []`, `degraded = true`
- **AND** SHALL NOT raise a 500 error

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