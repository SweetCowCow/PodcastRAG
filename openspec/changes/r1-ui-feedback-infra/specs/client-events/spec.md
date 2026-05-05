## ADDED Requirements

### Requirement: events ingestion endpoint accepts citation_click payloads

The backend SHALL expose `POST /events` accepting JSON body `{event_type: "citation_click", payload: {query_id: str, chunk_id: str, position: int}}`. The endpoint SHALL be public (no auth required) but SHALL apply per-IP rate limiting at 60 requests per minute, returning 429 when exceeded. When the request includes a valid `session_id` cookie, the resolved `user_id` SHALL be persisted on the event row; otherwise `user_id` SHALL be NULL. The endpoint SHALL validate that `event_type` is exactly `"citation_click"` (other values SHALL return 422) and that `payload` matches the citation_click schema (missing or extra keys SHALL return 422). On success the endpoint SHALL return 202 Accepted with empty body.

#### Scenario: Anonymous visitor reports a citation click

- **GIVEN** an unauthenticated visitor
- **WHEN** they `POST /events` with `{event_type: "citation_click", payload: {query_id: "q-1", chunk_id: "c-9", position: 2}}`
- **THEN** a row SHALL be inserted with `event_type="citation_click"`, `user_id=NULL`, `event_payload={query_id: "q-1", chunk_id: "c-9", position: 2}`
- **AND** the response status SHALL be 202

#### Scenario: Logged-in user's events tagged with user_id

- **GIVEN** an authenticated user U
- **WHEN** they `POST /events` with a valid citation_click payload
- **THEN** the inserted row SHALL have `user_id=U`

#### Scenario: Unknown event_type rejected

- **WHEN** the body contains `event_type: "scroll_depth"`
- **THEN** the response status SHALL be 422 (the body SHALL NOT be inserted)

#### Scenario: Payload schema mismatch rejected

- **WHEN** the body contains `{event_type: "citation_click", payload: {query_id: "q-1"}}` (missing chunk_id and position)
- **THEN** the response status SHALL be 422

#### Scenario: Per-IP rate limit enforced

- **GIVEN** an IP has sent 60 successful `POST /events` requests within the last 60 seconds
- **WHEN** the same IP sends one more request
- **THEN** the response status SHALL be 429

### Requirement: SourceCard fires citation_click event on user click

The QueryPage `<SourceCard>` component (the citation card rendered for each retrieved source under an AI answer) SHALL fire a `POST /events` request with `event_type="citation_click"` whenever the user clicks the card to navigate to the TranscriptPage. The request SHALL be sent via `navigator.sendBeacon` with a `fetch` keepalive fallback when `sendBeacon` is unavailable. The payload SHALL include `query_id` (the AI answer's query id), `chunk_id` (the source's chunk id), and `position` (zero-indexed position of the SourceCard within the answer's source list). The click event SHALL still trigger normal navigation regardless of whether the beacon succeeds.

#### Scenario: Click on second source card fires beacon

- **GIVEN** an AI answer with 4 SourceCards rendered
- **WHEN** the user clicks the SourceCard at index 1 (the second one) for chunk `c-42` of query `q-99`
- **THEN** exactly one `POST /events` SHALL fire with body `{event_type: "citation_click", payload: {query_id: "q-99", chunk_id: "c-42", position: 1}}`
- **AND** the application SHALL navigate to the TranscriptPage as it normally would

#### Scenario: sendBeacon unavailable falls back to fetch keepalive

- **GIVEN** a browser without `navigator.sendBeacon`
- **WHEN** a SourceCard click fires
- **THEN** a `fetch('/events', {method: 'POST', keepalive: true, body: ...})` SHALL be issued
