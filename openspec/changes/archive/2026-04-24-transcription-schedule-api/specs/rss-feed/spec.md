## ADDED Requirements

### Requirement: RSS preview endpoint

The backend SHALL expose `GET /rss-preview?url=<encoded_rss_url>` that fetches and parses the RSS feed at the given URL and returns a preview without creating any database records. The response SHALL include `title` (feed title), `episode_count` (total number of items in the feed), and `latest_published_at` (publication date of the most recent item, ISO 8601 string or null). The endpoint SHALL apply a 5-second HTTP timeout when fetching the remote feed.

#### Scenario: Valid RSS URL returns preview

- **WHEN** a client calls `GET /rss-preview?url=<valid_rss_url>` and the remote feed is reachable
- **THEN** the backend SHALL return HTTP 200 with `title`, `episode_count`, and `latest_published_at`

#### Scenario: Unreachable or invalid URL returns error

- **WHEN** a client calls `GET /rss-preview?url=<invalid_or_unreachable_url>` and the feed fetch fails or the response is not valid RSS/Atom
- **THEN** the backend SHALL return HTTP 422 with an error message describing the failure

#### Scenario: Remote feed times out

- **WHEN** the remote RSS URL does not respond within 5 seconds
- **THEN** the backend SHALL return HTTP 504 with an error message indicating timeout

#### Scenario: Frontend RSS preview uses real endpoint

- **WHEN** the user enters a RSS URL in the "Add Schedule" form and clicks the preview button
- **THEN** the frontend SHALL call `GET /rss-preview?url=<encoded_url>` and display the returned `title` and `episode_count`; the hardcoded setTimeout mock SHALL NOT be used
