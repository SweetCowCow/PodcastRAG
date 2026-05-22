# client-events Specification

## Purpose

TBD - created by archiving change 'r1-ui-feedback-infra'. Update Purpose after archive.

## Requirements

### Requirement: events ingestion endpoint accepts citation_click payloads

The backend SHALL expose `POST /events` accepting JSON body `{event_type: <enum>, payload: <object>}` where `event_type` is one of `"citation_click"` or `"search_executed"`. The endpoint SHALL be public (no auth required) but SHALL apply per-IP rate limiting at 60 requests per minute, returning 429 when exceeded. When the request includes a valid `session_id` cookie, the resolved `user_id` SHALL be persisted on the event row; otherwise `user_id` SHALL be NULL. The endpoint SHALL validate that `event_type` is one of the accepted enum values (other values SHALL return 422) and that `payload` matches the schema corresponding to `event_type` (missing or extra keys SHALL return 422). On success the endpoint SHALL return 202 Accepted with empty body.

The `citation_click` payload schema SHALL be `{query_id: str, chunk_id: str, position: int}`. The `search_executed` payload schema SHALL be `{show_id: str (UUID), query_text: str (length 1 to 500), mode: enum("semantic", "chat")}`.

#### Scenario: Anonymous visitor reports a citation click

- **GIVEN** an unauthenticated visitor
- **WHEN** they `POST /events` with `{event_type: "citation_click", payload: {query_id: "q-1", chunk_id: "c-9", position: 2}}`
- **THEN** a row SHALL be inserted with `event_type="citation_click"`, `user_id=NULL`, `event_payload={query_id: "q-1", chunk_id: "c-9", position: 2}`
- **AND** the response status SHALL be 202

#### Scenario: Logged-in user's events tagged with user_id

- **GIVEN** an authenticated user U
- **WHEN** they `POST /events` with a valid citation_click payload
- **THEN** the inserted row SHALL have `user_id=U`

#### Scenario: search_executed event accepted with valid payload

- **GIVEN** any visitor (authenticated or not)
- **WHEN** they `POST /events` with `{event_type: "search_executed", payload: {show_id: "<uuid>", query_text: "歌單", mode: "chat"}}`
- **THEN** a row SHALL be inserted with `event_type="search_executed"` and the matching payload
- **AND** the response status SHALL be 202

#### Scenario: Unknown event_type rejected

- **WHEN** the body contains `event_type: "scroll_depth"`
- **THEN** the response status SHALL be 422 (the body SHALL NOT be inserted)

#### Scenario: Payload schema mismatch rejected

- **WHEN** the body contains `{event_type: "citation_click", payload: {query_id: "q-1"}}` (missing chunk_id and position)
- **THEN** the response status SHALL be 422

#### Scenario: search_executed payload with unknown mode rejected

- **WHEN** the body contains `{event_type: "search_executed", payload: {show_id: "<uuid>", query_text: "x", mode: "keyword"}}`
- **THEN** the response status SHALL be 422

#### Scenario: search_executed payload with overlong query_text rejected

- **WHEN** the body contains a `search_executed` payload whose `query_text` is 501 characters long
- **THEN** the response status SHALL be 422

#### Scenario: Per-IP rate limit enforced

- **GIVEN** an IP has sent 60 successful `POST /events` requests within the last 60 seconds
- **WHEN** the same IP sends one more request
- **THEN** the response status SHALL be 429

---
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

<!-- @trace
source: r1-ui-feedback-infra
updated: 2026-05-05
code:
  - src/LandingPage.jsx
  - backend/alembic/versions/q5f6a7b8c9d0_add_qa_feedback_and_events.py
  - src/QueryPage.jsx
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/case-studies/zeabur-platform-case-study.md
  - docs/research/competitive-analysis.md
  - docs/case-studies/transcription-queue-discussion.md
  - aisteps-tab.png
  - backend/app/schemas/event.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/api/events.py
  - backend/app/api/qa_feedback.py
  - backend/app/main.py
  - backend/app/models/qa_feedback.py
  - backend/app/core/csrf.py
  - backend/app/schemas/query.py
  - backend/app/schemas/qa_feedback.py
  - docs/case-studies/build-zeabur-pptx.js
  - backend/app/api/query.py
  - src/PodcastSelect.jsx
  - docs/research/competitive-feature-plan.md
  - docs/research/r1-rag-eval-brief.md
  - backend/app/models/event.py
  - backend/app/core/rate_limit.py
  - index.html
  - backend/app/models/__init__.py
tests:
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_qa_feedback_stats.py
  - backend/tests/test_events_api.py
-->

---
### Requirement: QueryPage emits search_executed event after successful semantic or chat query

After a Semantic-mode or Chat-mode query in QueryPage successfully returns results, the frontend SHALL `POST /events` with `{event_type: "search_executed", payload: {show_id, query_text, mode}}` where `mode` is `"semantic"` or `"chat"` respectively. The request SHALL be sent via `navigator.sendBeacon` with a `fetch` keepalive fallback. The emission SHALL be best-effort: any network failure or non-2xx response SHALL be swallowed by the client and SHALL NOT surface as a user-visible error. The Index tab SHALL NOT emit `search_executed` events while it remains a placeholder.

#### Scenario: Successful chat query emits one search_executed event

- **GIVEN** an authenticated user on the Chat tab
- **WHEN** the user submits the query `歌單` and the chat endpoint returns a successful answer
- **THEN** the client SHALL issue exactly one `POST /events` with `event_type="search_executed"` and `payload.mode="chat"` and `payload.query_text="歌單"`

#### Scenario: Failed query does not emit search_executed

- **GIVEN** a query that fails with a 500 response
- **WHEN** the failure is observed by the client
- **THEN** no `search_executed` event SHALL be emitted

#### Scenario: Index tab does not emit search_executed

- **WHEN** a visitor types and submits a query in the Index tab placeholder
- **THEN** no `POST /events` request with `event_type="search_executed"` SHALL be issued

#### Scenario: Event emission failure does not surface to user

- **GIVEN** the `POST /events` request fails with a network error
- **WHEN** the failure occurs
- **THEN** no error toast, banner, or modal SHALL be shown to the user
- **AND** the user's query results SHALL still render normally
