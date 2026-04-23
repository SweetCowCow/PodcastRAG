## ADDED Requirements

### Requirement: RSS feed parser

The backend SHALL provide an async function that accepts an RSS feed URL and returns structured show metadata plus a list of episode metadata, supporting RSS 2.0 with iTunes extensions.

#### Scenario: Valid RSS feed parsed

- **WHEN** the parser is called with a URL returning a valid RSS 2.0 feed
- **THEN** it SHALL return a show object (title, description, image_url, language) and a list of episode objects (title, description, audio_url, duration_seconds, published_at, guid)

#### Scenario: Invalid feed URL rejected

- **WHEN** the parser is called with a URL returning HTTP 404, non-XML content, or XML without a channel element
- **THEN** it SHALL raise a descriptive parser error identifying the failure reason

#### Scenario: Feed without iTunes extensions parsed

- **WHEN** the parser is called with a plain RSS 2.0 feed lacking iTunes tags
- **THEN** it SHALL still return show and episode data, leaving iTunes-specific fields (duration_seconds, image_url) as null when absent

### Requirement: Create show endpoint

The backend SHALL expose `POST /shows` that accepts an RSS URL, parses the feed, persists the show and its initial episodes (up to 200), and returns the created show with episode count.

#### Scenario: New show created

- **WHEN** `POST /shows` is called with body `{"rss_url": "<url>"}` and the URL is not yet registered
- **THEN** the response SHALL be HTTP 201 with the new show record (id, title, rss_url, etc.) and `episode_count` reflecting the number of episodes persisted

#### Scenario: Duplicate RSS URL rejected

- **WHEN** `POST /shows` is called with an `rss_url` matching an existing show
- **THEN** the response SHALL be HTTP 409 with an error message indicating the feed is already registered

#### Scenario: Invalid RSS feed rejected

- **WHEN** `POST /shows` is called with a URL that fails to parse
- **THEN** the response SHALL be HTTP 400 with an error message describing the parse failure, and no show record SHALL be persisted

### Requirement: List shows endpoint

The backend SHALL expose `GET /shows` returning all registered shows ordered by `created_at` descending.

#### Scenario: Shows listed

- **WHEN** `GET /shows` is called and 3 shows exist
- **THEN** the response SHALL be HTTP 200 with a JSON array of 3 show records ordered newest-first

#### Scenario: No shows yet

- **WHEN** `GET /shows` is called with an empty `shows` table
- **THEN** the response SHALL be HTTP 200 with an empty JSON array

### Requirement: Get show by id endpoint

The backend SHALL expose `GET /shows/{show_id}` returning the show record for the given UUID.

#### Scenario: Show found

- **WHEN** `GET /shows/{show_id}` is called with a valid existing UUID
- **THEN** the response SHALL be HTTP 200 with the full show record including `episode_count`

#### Scenario: Show not found

- **WHEN** `GET /shows/{show_id}` is called with a UUID that does not exist
- **THEN** the response SHALL be HTTP 404 with an error message

### Requirement: Delete show endpoint

The backend SHALL expose `DELETE /shows/{show_id}` which removes the show and cascades to its episodes and transcripts.

#### Scenario: Show deleted

- **WHEN** `DELETE /shows/{show_id}` is called for an existing show
- **THEN** the response SHALL be HTTP 204, and the show plus all its episodes SHALL be removed from the database

#### Scenario: Delete missing show

- **WHEN** `DELETE /shows/{show_id}` is called for a non-existent UUID
- **THEN** the response SHALL be HTTP 404

### Requirement: Sync show episodes endpoint

The backend SHALL expose `POST /shows/{show_id}/sync` which re-fetches the RSS feed and upserts episodes by `(show_id, guid)`.

#### Scenario: Sync adds new episodes

- **WHEN** `POST /shows/{show_id}/sync` is called and the feed has 5 episodes newer than any stored
- **THEN** the response SHALL be HTTP 200 with `{"added": 5, "updated": 0, "total": <total>}` and the new episodes SHALL be persisted

#### Scenario: Sync updates existing episodes

- **WHEN** sync runs against a feed whose existing episodes have updated titles or descriptions
- **THEN** matching episodes (by `guid`) SHALL be updated in place and the response SHALL include `"updated": <n>`

#### Scenario: Sync is idempotent

- **WHEN** sync is called twice in a row without feed changes
- **THEN** the second call SHALL return `{"added": 0, "updated": 0, ...}` and no duplicate episodes SHALL be created

### Requirement: List episodes endpoint

The backend SHALL expose `GET /shows/{show_id}/episodes` returning episodes for the given show, supporting pagination via `limit` and `offset` query parameters.

#### Scenario: Episodes listed with default pagination

- **WHEN** `GET /shows/{show_id}/episodes` is called without pagination parameters
- **THEN** the response SHALL be HTTP 200 with up to 50 episodes ordered by `published_at` descending

#### Scenario: Episodes listed with custom pagination

- **WHEN** `GET /shows/{show_id}/episodes?limit=10&offset=20` is called
- **THEN** the response SHALL return episodes 21–30 ordered by `published_at` descending

#### Scenario: Show with no episodes

- **WHEN** `GET /shows/{show_id}/episodes` is called for a show with zero episodes
- **THEN** the response SHALL be HTTP 200 with an empty array
