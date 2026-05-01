# rss-feed Specification

## Purpose

TBD - created by archiving change 'rss-feed'. Update Purpose after archive.

## Requirements

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


<!-- @trace
source: rss-feed
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/.dockerignore
  - backend/app/models/show.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/models/__init__.py
  - backend/app/services/__init__.py
  - backend/app/api/shows.py
  - backend/app/api/episodes.py
  - backend/app/schemas/episode.py
  - backend/alembic.ini
  - backend/app/core/__init__.py
  - backend/Dockerfile
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/alembic/script.py.mako
  - backend/app/api/__init__.py
  - backend/app/schemas/__init__.py
  - backend/.env.example
  - backend/requirements.txt
  - backend/app/__init__.py
  - backend/app/services/rss_parser.py
  - backend/alembic/README
  - .spectra/spectra.db
  - backend/app/core/database.py
  - backend/app/schemas/sync.py
  - backend/alembic/env.py
  - backend/app/main.py
  - backend/docker-compose.yml
  - backend/app/models/episode.py
-->

---
### Requirement: Create show endpoint

The backend SHALL expose `POST /shows` that accepts an RSS URL, parses the feed, persists the show and all episodes returned by the feed, and returns the created show with episode count. The parser SHALL NOT impose an arbitrary upper bound on the number of episodes persisted from a single feed; if the feed contains 1 episode or 1000 episodes, all SHALL be persisted. The endpoint SHALL catch RSS parsing and timeout exceptions and convert them to HTTP errors whose body matches the unified error response schema, mapping `RssParseError` to HTTP 422 with `error_code = "rss_invalid"` and `httpx.TimeoutException` (or `asyncio.TimeoutError`) to HTTP 504 with `error_code = "rss_timeout"`.

#### Scenario: New show created

- **WHEN** `POST /shows` is called with body `{"rss_url": "<url>"}` and the URL is not yet registered
- **THEN** the response SHALL be HTTP 201 with the new show record (id, title, rss_url, etc.) and `episode_count` reflecting the number of episodes persisted

#### Scenario: Duplicate RSS URL rejected

- **WHEN** `POST /shows` is called with an `rss_url` matching an existing show
- **THEN** the response SHALL be HTTP 409 with body `{"detail": {"error_code": "show_duplicate_rss", "provider": null, "detail": <message>}}`

#### Scenario: Invalid RSS feed rejected

- **WHEN** `POST /shows` is called with a URL whose response cannot be parsed as a valid RSS feed
- **THEN** the response SHALL be HTTP 422 with body `{"detail": {"error_code": "rss_invalid", "provider": null, "detail": <message>}}` and no show record SHALL be persisted

#### Scenario: RSS fetch timeout returns 504

- **WHEN** `POST /shows` is called with a URL whose remote server does not respond within the configured timeout
- **THEN** the response SHALL be HTTP 504 with body `{"detail": {"error_code": "rss_timeout", "provider": null, "detail": <message>}}` and no show record SHALL be persisted

#### Scenario: Feed with more than 200 episodes is persisted in full

- **WHEN** `POST /shows` is called with an RSS feed URL whose XML contains 251 `<item>` elements
- **THEN** the response SHALL be HTTP 201 and `episode_count` SHALL equal 251
- **AND** the `episodes` table SHALL contain 251 rows linked to the new show's `show_id`

##### Example: Firstory feed with 251 items

- **GIVEN** an RSS feed XML containing 251 valid `<item>` elements with audio enclosures
- **WHEN** the parser processes the feed via the default call signature `fetch_and_parse(url)` (no `max_episodes` argument)
- **THEN** the returned `ParsedFeed.episodes` list SHALL contain 251 `ParsedEpisode` objects (not 200)


<!-- @trace
source: friendly-external-api-errors
updated: 2026-05-01
code:
  - backend/app/main.py
  - backend/app/api/shows.py
  - src/i18n.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/errors.py
  - src/QueryPage.jsx
  - backend/app/services/llm_config.py
  - backend/app/api/query.py
  - index.html
tests:
  - backend/tests/test_provider_label.py
  - backend/tests/conftest.py
  - backend/tests/test_error_responses.py
-->

---
### Requirement: List shows endpoint

The backend SHALL expose `GET /shows` returning all registered shows ordered by `created_at` descending. Each show record in the response SHALL include `id`, `title`, `description`, `rss_url`, `image_url`, `language`, `created_at`, `episode_count`, and `transcribed_count`. The `transcribed_count` SHALL equal the number of episodes belonging to the show whose `transcripts.status` is `'completed'`.

#### Scenario: Shows listed with episode and transcript counts

- **WHEN** `GET /shows` is called and a show has 10 episodes of which 3 have a linked `transcripts` row with `status = 'completed'`
- **THEN** the response record for that show SHALL contain `episode_count = 10` and `transcribed_count = 3`

#### Scenario: Show with no transcribed episodes

- **WHEN** `GET /shows` is called and a show has 5 episodes but none has a `completed` transcript
- **THEN** the response record for that show SHALL contain `transcribed_count = 0`

#### Scenario: Shows listed ordered newest-first

- **WHEN** `GET /shows` is called and 3 shows exist
- **THEN** the response SHALL be HTTP 200 with a JSON array of 3 show records ordered by `created_at` descending, each containing the full set of fields above

#### Scenario: No shows yet

- **WHEN** `GET /shows` is called with an empty `shows` table
- **THEN** the response SHALL be HTTP 200 with an empty JSON array


<!-- @trace
source: shows-list-backend
updated: 2026-04-23
code:
  - backend/app/api/shows.py
  - src/PodcastSelect.jsx
  - backend/app/schemas/show.py
  - src/QueryPage.jsx
-->

---
### Requirement: Get show by id endpoint

The backend SHALL expose `GET /shows/{show_id}` returning the show record for the given UUID.

#### Scenario: Show found

- **WHEN** `GET /shows/{show_id}` is called with a valid existing UUID
- **THEN** the response SHALL be HTTP 200 with the full show record including `episode_count`

#### Scenario: Show not found

- **WHEN** `GET /shows/{show_id}` is called with a UUID that does not exist
- **THEN** the response SHALL be HTTP 404 with an error message


<!-- @trace
source: rss-feed
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/.dockerignore
  - backend/app/models/show.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/models/__init__.py
  - backend/app/services/__init__.py
  - backend/app/api/shows.py
  - backend/app/api/episodes.py
  - backend/app/schemas/episode.py
  - backend/alembic.ini
  - backend/app/core/__init__.py
  - backend/Dockerfile
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/alembic/script.py.mako
  - backend/app/api/__init__.py
  - backend/app/schemas/__init__.py
  - backend/.env.example
  - backend/requirements.txt
  - backend/app/__init__.py
  - backend/app/services/rss_parser.py
  - backend/alembic/README
  - .spectra/spectra.db
  - backend/app/core/database.py
  - backend/app/schemas/sync.py
  - backend/alembic/env.py
  - backend/app/main.py
  - backend/docker-compose.yml
  - backend/app/models/episode.py
-->

---
### Requirement: Delete show endpoint

The backend SHALL expose `DELETE /shows/{show_id}` which removes the show and cascades to its episodes and transcripts.

#### Scenario: Show deleted

- **WHEN** `DELETE /shows/{show_id}` is called for an existing show
- **THEN** the response SHALL be HTTP 204, and the show plus all its episodes SHALL be removed from the database

#### Scenario: Delete missing show

- **WHEN** `DELETE /shows/{show_id}` is called for a non-existent UUID
- **THEN** the response SHALL be HTTP 404


<!-- @trace
source: rss-feed
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/.dockerignore
  - backend/app/models/show.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/models/__init__.py
  - backend/app/services/__init__.py
  - backend/app/api/shows.py
  - backend/app/api/episodes.py
  - backend/app/schemas/episode.py
  - backend/alembic.ini
  - backend/app/core/__init__.py
  - backend/Dockerfile
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/alembic/script.py.mako
  - backend/app/api/__init__.py
  - backend/app/schemas/__init__.py
  - backend/.env.example
  - backend/requirements.txt
  - backend/app/__init__.py
  - backend/app/services/rss_parser.py
  - backend/alembic/README
  - .spectra/spectra.db
  - backend/app/core/database.py
  - backend/app/schemas/sync.py
  - backend/alembic/env.py
  - backend/app/main.py
  - backend/docker-compose.yml
  - backend/app/models/episode.py
-->

---
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


<!-- @trace
source: rss-feed
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/.dockerignore
  - backend/app/models/show.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/models/__init__.py
  - backend/app/services/__init__.py
  - backend/app/api/shows.py
  - backend/app/api/episodes.py
  - backend/app/schemas/episode.py
  - backend/alembic.ini
  - backend/app/core/__init__.py
  - backend/Dockerfile
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/alembic/script.py.mako
  - backend/app/api/__init__.py
  - backend/app/schemas/__init__.py
  - backend/.env.example
  - backend/requirements.txt
  - backend/app/__init__.py
  - backend/app/services/rss_parser.py
  - backend/alembic/README
  - .spectra/spectra.db
  - backend/app/core/database.py
  - backend/app/schemas/sync.py
  - backend/alembic/env.py
  - backend/app/main.py
  - backend/docker-compose.yml
  - backend/app/models/episode.py
-->

---
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

<!-- @trace
source: rss-feed
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/.dockerignore
  - backend/app/models/show.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/models/__init__.py
  - backend/app/services/__init__.py
  - backend/app/api/shows.py
  - backend/app/api/episodes.py
  - backend/app/schemas/episode.py
  - backend/alembic.ini
  - backend/app/core/__init__.py
  - backend/Dockerfile
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/alembic/script.py.mako
  - backend/app/api/__init__.py
  - backend/app/schemas/__init__.py
  - backend/.env.example
  - backend/requirements.txt
  - backend/app/__init__.py
  - backend/app/services/rss_parser.py
  - backend/alembic/README
  - .spectra/spectra.db
  - backend/app/core/database.py
  - backend/app/schemas/sync.py
  - backend/alembic/env.py
  - backend/app/main.py
  - backend/docker-compose.yml
  - backend/app/models/episode.py
-->

---
### Requirement: RSS preview endpoint

The backend SHALL expose `GET /rss-preview?url=<encoded_rss_url>` that fetches and parses the RSS feed at the given URL and returns a preview without creating any database records. The response SHALL include `title` (feed title), `episode_count` (total number of items in the feed), and `latest_published_at` (publication date of the most recent item, ISO 8601 string or null). The endpoint SHALL apply a 5-second HTTP timeout when fetching the remote feed. Error responses SHALL match the unified error response schema, mapping parse failures to HTTP 422 with `error_code = "rss_invalid"` and timeouts to HTTP 504 with `error_code = "rss_timeout"`.

#### Scenario: Valid RSS URL returns preview

- **WHEN** a client calls `GET /rss-preview?url=<valid_rss_url>` and the remote feed is reachable
- **THEN** the backend SHALL return HTTP 200 with `title`, `episode_count`, and `latest_published_at`

#### Scenario: Invalid feed returns 422 with rss_invalid

- **WHEN** a client calls `GET /rss-preview?url=<invalid_url>` and the response is not valid RSS/Atom
- **THEN** the backend SHALL return HTTP 422 with body `{"detail": {"error_code": "rss_invalid", "provider": null, "detail": <message>}}`

#### Scenario: Remote feed times out

- **WHEN** the remote RSS URL does not respond within 5 seconds
- **THEN** the backend SHALL return HTTP 504 with body `{"detail": {"error_code": "rss_timeout", "provider": null, "detail": <message>}}`

#### Scenario: Frontend RSS preview uses real endpoint

- **WHEN** the user enters a RSS URL in the "Add Schedule" form and clicks the preview button
- **THEN** the frontend SHALL call `GET /rss-preview?url=<encoded_url>` and display the returned `title` and `episode_count`; the hardcoded setTimeout mock SHALL NOT be used

<!-- @trace
source: friendly-external-api-errors
updated: 2026-05-01
code:
  - backend/app/main.py
  - backend/app/api/shows.py
  - src/i18n.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/errors.py
  - src/QueryPage.jsx
  - backend/app/services/llm_config.py
  - backend/app/api/query.py
  - index.html
tests:
  - backend/tests/test_provider_label.py
  - backend/tests/conftest.py
  - backend/tests/test_error_responses.py
-->