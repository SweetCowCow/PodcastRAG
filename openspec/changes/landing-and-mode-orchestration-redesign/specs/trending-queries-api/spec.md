## ADDED Requirements

### Requirement: GET trending-queries endpoint returns popular query strings per show

The backend SHALL expose `GET /shows/{show_id}/trending-queries` accepting an optional query parameter `days` (integer, default 7, valid range 1 to 30). The endpoint SHALL be public (no authentication required) and SHALL apply the same per-IP rate limit as `POST /events` (60 requests per minute). The endpoint SHALL query the `events` table for rows with `event_type = 'search_executed'`, `created_at >= now() - interval ':days days'`, and `payload->>'show_id' = :show_id`, group by `payload->>'query_text'`, filter to groups with `count(*) >= :cutoff` (where `cutoff` is configured via environment variable with default 3), order by `count(*)` descending, and return up to 10 rows.

The response body SHALL be `{queries: [{query_text: string, count: integer}], days: integer, cutoff: integer}`. When the show id is not found in the `shows` table the endpoint SHALL return 404. When no queries meet the cutoff the endpoint SHALL return 200 with `queries: []`. When the database query fails the endpoint SHALL return 500.

#### Scenario: Returns popular queries above cutoff sorted by count

- **GIVEN** the `events` table contains, within the last 7 days for show S, the query `歌單` 5 times and `來賓推薦` 3 times and `世運` 1 time, all with `event_type='search_executed'`
- **WHEN** a client calls `GET /shows/S/trending-queries?days=7`
- **THEN** the response SHALL be 200 with `queries: [{query_text: "歌單", count: 5}, {query_text: "來賓推薦", count: 3}]`
- **AND** the query `世運` SHALL NOT appear in the response

#### Scenario: Returns empty list when no query meets the cutoff

- **GIVEN** the `events` table contains only queries with count below the configured cutoff for show S
- **WHEN** a client calls `GET /shows/S/trending-queries?days=7`
- **THEN** the response SHALL be 200 with `queries: []`

#### Scenario: Returns 404 for unknown show id

- **GIVEN** show id `unknown` does not exist in the `shows` table
- **WHEN** a client calls `GET /shows/unknown/trending-queries`
- **THEN** the response status SHALL be 404

#### Scenario: Rejects days parameter outside allowed range

- **WHEN** a client calls `GET /shows/S/trending-queries?days=99`
- **THEN** the response status SHALL be 422

### Requirement: HomePage and QueryPage call trending-queries and render chips

The `HomePage` show grid and the `QueryPage` Semantic and Chat tabs SHALL call `GET /shows/{show_id}/trending-queries?days=7` and render up to 5 chips representing the returned `query_text` strings. Clicking a chip SHALL set the QueryPage input value to that string and immediately submit the query in the currently active mode. If the endpoint returns an empty list or fails, no chip section SHALL render (silent fallback) and no user-facing error message SHALL be shown.

#### Scenario: Chips render in count-descending order, limited to five

- **GIVEN** the endpoint returns 8 queries
- **WHEN** the chip section renders
- **THEN** exactly the top 5 queries SHALL be rendered as chips in count-descending order

#### Scenario: Empty endpoint response hides chip section silently

- **GIVEN** the endpoint returns `queries: []`
- **WHEN** the chip section would render
- **THEN** no chip section SHALL appear in the DOM
- **AND** no error message SHALL be shown

#### Scenario: Clicking a chip submits the query in active mode

- **GIVEN** the user is on the Chat tab and chips are rendered
- **WHEN** the user clicks a chip with text `歌單`
- **THEN** the input SHALL become `歌單`
- **AND** a Chat-mode query SHALL be submitted for `歌單` without further user action
