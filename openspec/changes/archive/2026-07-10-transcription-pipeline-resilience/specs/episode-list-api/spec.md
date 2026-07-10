## MODIFIED Requirements

### Requirement: QueryPage episode panel fetches real episodes

The QueryPage frontend SHALL fetch `GET /shows/{show_id}/episodes?limit=200` on mount and render the returned list in the right-side episode panel. The panel SHALL display for each episode: `title`, publication date formatted as `YYYY-MM-DD`, duration formatted as `mm:ss` from `duration_seconds`, and a transcription status badge with three states: `"completed"` → 已轉錄/Done (success variant), `"failed"` → 轉錄失敗/Failed (danger variant), any other value or `null` → 待轉錄/Pending (muted variant). Episodes whose `transcript_status` is NOT `"completed"` SHALL be rendered with reduced opacity (0.45) and SHALL NOT be clickable.

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

#### Scenario: Failed episode shows a failed badge

- **WHEN** an episode card has `transcript_status = "failed"`
- **THEN** the card SHALL display the 轉錄失敗/Failed badge (danger variant) instead of 待轉錄/Pending
- **AND** the card SHALL NOT be clickable

#### Scenario: Pending and processing episodes still show the pending badge

- **WHEN** an episode card has `transcript_status` of `null`, `"pending"`, or `"processing"`
- **THEN** the card SHALL display the 待轉錄/Pending badge (muted variant)
