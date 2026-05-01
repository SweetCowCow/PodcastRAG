## MODIFIED Requirements

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
