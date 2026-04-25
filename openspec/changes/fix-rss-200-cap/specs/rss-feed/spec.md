## MODIFIED Requirements

### Requirement: Create show endpoint

The backend SHALL expose `POST /shows` that accepts an RSS URL, parses the feed, persists the show and all episodes returned by the feed, and returns the created show with episode count. The parser SHALL NOT impose an arbitrary upper bound on the number of episodes persisted from a single feed; if the feed contains 1 episode or 1000 episodes, all SHALL be persisted.

#### Scenario: New show created

- **WHEN** `POST /shows` is called with body `{"rss_url": "<url>"}` and the URL is not yet registered
- **THEN** the response SHALL be HTTP 201 with the new show record (id, title, rss_url, etc.) and `episode_count` reflecting the number of episodes persisted

#### Scenario: Duplicate RSS URL rejected

- **WHEN** `POST /shows` is called with an `rss_url` matching an existing show
- **THEN** the response SHALL be HTTP 409 with an error message indicating the feed is already registered

#### Scenario: Invalid RSS feed rejected

- **WHEN** `POST /shows` is called with a URL that fails to parse
- **THEN** the response SHALL be HTTP 400 with an error message describing the parse failure, and no show record SHALL be persisted

#### Scenario: Feed with more than 200 episodes is persisted in full

- **WHEN** `POST /shows` is called with an RSS feed URL whose XML contains 251 `<item>` elements
- **THEN** the response SHALL be HTTP 201 and `episode_count` SHALL equal 251
- **AND** the `episodes` table SHALL contain 251 rows linked to the new show's `show_id`

##### Example: Firstory feed with 251 items

- **GIVEN** an RSS feed XML containing 251 valid `<item>` elements with audio enclosures
- **WHEN** the parser processes the feed via the default call signature `fetch_and_parse(url)` (no `max_episodes` argument)
- **THEN** the returned `ParsedFeed.episodes` list SHALL contain 251 `ParsedEpisode` objects (not 200)

