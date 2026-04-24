## ADDED Requirements

### Requirement: Episodes endpoint includes transcript status

The `GET /shows/{show_id}/episodes` endpoint SHALL return each episode's `transcript_status` field. The value SHALL be one of `"completed"`, `"processing"`, `"pending"`, `"failed"`, or `null` (when no transcript row exists). The backend SHALL derive this by LEFT JOIN-ing the `transcripts` table on `episode_id` and reading `transcripts.status`.

#### Scenario: Episode with completed transcript

- **WHEN** a client calls `GET /shows/{show_id}/episodes` and one episode has a transcript row with `status = 'completed'`
- **THEN** that episode's `transcript_status` in the response SHALL equal `"completed"`

#### Scenario: Episode with no transcript

- **WHEN** a client calls `GET /shows/{show_id}/episodes` and one episode has no row in the `transcripts` table
- **THEN** that episode's `transcript_status` in the response SHALL equal `null`

#### Scenario: Episode with failed transcript

- **WHEN** a client calls `GET /shows/{show_id}/episodes` and one episode has a transcript row with `status = 'failed'`
- **THEN** that episode's `transcript_status` in the response SHALL equal `"failed"`

### Requirement: QueryPage episode panel fetches real episodes

The QueryPage frontend SHALL fetch `GET /shows/{show_id}/episodes?limit=200` on mount and render the returned list in the right-side episode panel. The panel SHALL display for each episode: `title`, publication date formatted as `YYYY-MM-DD`, duration formatted as `mm:ss` from `duration_seconds`, and a transcription status badge (`"completed"` → 已轉錄/Done; any other value or `null` → 待轉錄/Pending). Episodes whose `transcript_status` is NOT `"completed"` SHALL be rendered with reduced opacity (0.45) and SHALL NOT be clickable.

#### Scenario: Panel shows real episodes on load

- **WHEN** QueryPage mounts and `GET /shows/{show_id}/episodes` returns a non-empty array
- **THEN** the episode panel SHALL render one card per episode using the API-returned `title`, formatted `published_at`, formatted `duration_seconds`, and `transcript_status`

#### Scenario: Panel shows loading state

- **WHEN** QueryPage mounts and the episodes fetch is in flight
- **THEN** the episode panel SHALL display a loading indicator instead of episode cards

#### Scenario: Panel shows error state

- **WHEN** the episodes fetch fails with a non-2xx response or network error
- **THEN** the episode panel SHALL display an error message and SHALL NOT render episode cards

#### Scenario: Non-transcribed episode is not clickable

- **WHEN** an episode card has `transcript_status` other than `"completed"`
- **THEN** clicking the card SHALL have no effect and the card cursor SHALL be `default`
