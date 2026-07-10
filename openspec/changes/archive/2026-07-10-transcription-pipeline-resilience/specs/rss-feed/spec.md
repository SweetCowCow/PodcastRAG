## MODIFIED Requirements

### Requirement: Sync show episodes endpoint

The backend SHALL expose `POST /shows/{show_id}/sync` which re-fetches the RSS feed and upserts episodes by `(show_id, guid)`.

When sync updates an existing episode and the episode's `audio_url` value has changed, sync SHALL also set that episode's `audio_storage_key` to NULL, so the next transcription attempt re-downloads and re-uploads the audio from the new URL instead of reusing the stale object in storage. Episodes whose `audio_url` is unchanged SHALL keep their `audio_storage_key` untouched, regardless of other field updates.

#### Scenario: Sync adds new episodes

- **WHEN** `POST /shows/{show_id}/sync` is called and the feed has 5 episodes newer than any stored
- **THEN** the response SHALL be HTTP 200 with `{"added": 5, "updated": 0, "total": <total>}` and the new episodes SHALL be persisted

#### Scenario: Sync updates existing episodes

- **WHEN** sync runs against a feed whose existing episodes have updated titles or descriptions
- **THEN** matching episodes (by `guid`) SHALL be updated in place and the response SHALL include `"updated": <n>`

#### Scenario: Sync is idempotent

- **WHEN** sync is called twice in a row without feed changes
- **THEN** the second call SHALL return `{"added": 0, "updated": 0, ...}` and no duplicate episodes SHALL be created

#### Scenario: Changed audio_url invalidates the stored audio object

- **GIVEN** an existing episode with `audio_storage_key` set and a feed entry (same guid) whose `audio_url` differs from the stored value
- **WHEN** sync runs
- **THEN** the episode's `audio_url` SHALL be updated to the new value
- **AND** the episode's `audio_storage_key` SHALL be NULL

#### Scenario: Unchanged audio_url keeps the stored audio object

- **GIVEN** an existing episode with `audio_storage_key` set and a feed entry (same guid) with an updated title but identical `audio_url`
- **WHEN** sync runs
- **THEN** the episode's `audio_storage_key` SHALL remain unchanged
