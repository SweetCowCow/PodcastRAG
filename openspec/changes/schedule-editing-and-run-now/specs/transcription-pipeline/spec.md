## ADDED Requirements

### Requirement: Transcribe-latest endpoint syncs then enqueues newest N unfinished episodes

The backend SHALL expose `POST /shows/{show_id}/transcribe-latest` that (1) synchronises episodes from the show's RSS feed (equivalent to `POST /shows/{show_id}/sync`), then (2) selects the newest episodes whose transcript status is not `completed` (including episodes with no transcript, or with status `pending`, `processing`, or `failed`), limited to `max_episodes`, and (3) creates or resets each selected transcript to `pending` and enqueues a Celery `transcribe_episode` task for it. The endpoint SHALL respond with HTTP 202 and a JSON body `{ "queued": <int>, "synced": { "added": <int>, "updated": <int> } }`.

The effective `max_episodes` SHALL be resolved in this order: (1) the `max_episodes` query parameter if provided and greater than zero, (2) `show_schedules.max_episodes` if the show has a schedule row and the stored value is greater than zero, (3) the fallback default of `5`.

#### Scenario: Query parameter overrides schedule value

- **WHEN** a client calls `POST /shows/{show_id}/transcribe-latest?max_episodes=3` and the show's schedule has `max_episodes=10`
- **THEN** the backend SHALL select at most 3 episodes to enqueue

#### Scenario: Schedule value used when query parameter absent

- **WHEN** a client calls `POST /shows/{show_id}/transcribe-latest` without query parameters and the show's schedule has `max_episodes=7`
- **THEN** the backend SHALL select at most 7 episodes to enqueue

#### Scenario: Default applied when no schedule exists

- **WHEN** a client calls `POST /shows/{show_id}/transcribe-latest` without query parameters and the show has no schedule row
- **THEN** the backend SHALL select at most 5 episodes to enqueue

#### Scenario: Selection ordered by published_at descending

- **WHEN** a show has 10 unfinished episodes published on different dates and the effective `max_episodes` is 3
- **THEN** the backend SHALL enqueue exactly the 3 episodes with the most recent `published_at` timestamps

#### Scenario: Episodes already completed are skipped

- **WHEN** a show has 8 episodes of which 5 have `transcript.status = 'completed'` and 3 have no transcript, and `max_episodes=10`
- **THEN** only the 3 unfinished episodes SHALL be enqueued; `queued` in the response SHALL equal 3

#### Scenario: Sync counts included in response

- **WHEN** the sync step discovers 2 new episodes and updates 1 existing episode before enqueuing
- **THEN** the response body SHALL include `synced.added = 2` and `synced.updated = 1`

#### Scenario: Show not found returns 404

- **WHEN** a client calls `POST /shows/{show_id}/transcribe-latest` with a `show_id` that does not exist
- **THEN** the backend SHALL return HTTP 404

### Requirement: Sync logic is reusable across endpoints

The RSS synchronisation logic invoked by `POST /shows/{show_id}/sync` and `POST /shows/{show_id}/transcribe-latest` SHALL live in a single shared helper (e.g. `app.services.sync.sync_show_episodes`). Both endpoints SHALL call this helper rather than duplicate the upsert loop. The helper SHALL return a `{ added: int, updated: int, total: int }` summary without coupling to HTTP response models.

#### Scenario: Both endpoints observe identical sync behavior

- **WHEN** `POST /shows/{show_id}/sync` and `POST /shows/{show_id}/transcribe-latest` are called sequentially on the same show without external RSS changes between the two calls
- **THEN** the second call's `synced.added` SHALL be 0 and `synced.updated` SHALL be 0 (all episodes already present and up-to-date from the first call)
