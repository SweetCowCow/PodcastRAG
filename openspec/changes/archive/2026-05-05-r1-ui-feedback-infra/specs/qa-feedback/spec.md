## ADDED Requirements

### Requirement: qa_feedback API accepts authenticated thumbs vote with optional comment

The backend SHALL expose `POST /qa-feedback` accepting JSON body `{query_id: str, vote: "up" | "down", comment: str | null}`. The endpoint SHALL require an authenticated session; unauthenticated requests SHALL return 401. On success the endpoint SHALL insert a new `qa_feedback` row (it MUST NOT update an existing row even if the same user previously voted on the same `query_id`) and return 201 with `{id, vote, created_at}`.

#### Scenario: Logged-in user submits thumbs-up vote

- **GIVEN** an authenticated user U sends `POST /qa-feedback` with `{query_id: "q-123", vote: "up", comment: null}`
- **WHEN** the request is processed
- **THEN** a new row SHALL be inserted into `qa_feedback` with `user_id=U`, `query_id="q-123"`, `vote="up"`, `comment=NULL`
- **AND** the response status SHALL be 201

#### Scenario: User changes their vote on the same query

- **GIVEN** an authenticated user U has previously inserted a `qa_feedback` row for `query_id="q-123"` with `vote="up"`
- **WHEN** U sends `POST /qa-feedback` with `{query_id: "q-123", vote: "down", comment: "Wrong context"}`
- **THEN** a NEW row SHALL be inserted (the old row SHALL remain untouched)
- **AND** the qa_feedback table SHALL contain at least 2 rows for `(user_id=U, query_id="q-123")`

#### Scenario: Anonymous request rejected

- **GIVEN** a request without a valid `session_id` cookie
- **WHEN** `POST /qa-feedback` is called
- **THEN** the response status SHALL be 401

#### Scenario: Invalid vote value rejected

- **WHEN** the request body contains `{vote: "maybe"}`
- **THEN** the response status SHALL be 422

### Requirement: qa-feedback admin stats endpoint returns 7-day thumbs ratio

The backend SHALL expose `GET /qa-feedback/stats` requiring `admin` role. The endpoint SHALL return `{up_7d: int, down_7d: int, total_7d: int, ratio: float | null}` where:
- `up_7d` and `down_7d` count the LATEST vote per `(user_id, query_id)` pair within the last 7 days (rolling)
- `ratio` SHALL be `up_7d / total_7d` rounded to 2 decimals when `total_7d > 0`, otherwise `null`

Non-admin authenticated users SHALL receive 403; unauthenticated users SHALL receive 401.

#### Scenario: Admin reads stats with mixed votes

- **GIVEN** within the last 7 days the latest votes per (user, query) pair are: 8 up, 2 down
- **WHEN** an admin sends `GET /qa-feedback/stats`
- **THEN** the response SHALL be `{up_7d: 8, down_7d: 2, total_7d: 10, ratio: 0.80}`

#### Scenario: Admin reads stats when no votes exist

- **GIVEN** zero qa_feedback rows in the last 7 days
- **WHEN** an admin requests stats
- **THEN** the response SHALL be `{up_7d: 0, down_7d: 0, total_7d: 0, ratio: null}`

#### Scenario: Re-vote does not double-count

- **GIVEN** user U voted "up" on q-1 then changed to "down" on q-1, both within 7 days
- **WHEN** stats are computed
- **THEN** the (U, q-1) pair SHALL contribute exactly 1 down vote (the latest), not 1 up + 1 down

#### Scenario: Non-admin gets 403

- **GIVEN** an authenticated user with role=`user`
- **WHEN** they request `/qa-feedback/stats`
- **THEN** the response status SHALL be 403

### Requirement: QueryPage renders thumbs vote UI for AI answers

The frontend QueryPage SHALL render thumbs-up and thumbs-down buttons immediately below each AI summary answer block. When the visitor is unauthenticated the buttons SHALL be visually disabled and SHALL display a tooltip `登入後可投票` (`zh`) / `Sign in to vote` (`en`) on hover; clicking SHALL not trigger a network request and SHALL not open the LoginModal. When the visitor is authenticated, clicking thumbs-up SHALL `POST /qa-feedback` with `{vote: "up", comment: null}`; clicking thumbs-down SHALL expand an inline comment textarea with a Send button — submitting the textarea SHALL `POST /qa-feedback` with the typed comment (or `null` if blank). After a successful vote the corresponding button SHALL display in the accent color and the text `已收到 ✓` (`zh`) / `Recorded ✓` (`en`) SHALL appear next to the buttons; the visitor SHALL be able to click the opposite button to change their vote (which fires a new POST).

#### Scenario: Anonymous visitor sees disabled thumbs

- **GIVEN** the visitor is not logged in
- **WHEN** an AI answer renders
- **THEN** thumbs-up and thumbs-down buttons SHALL be visible but disabled (cursor shows `not-allowed`)
- **AND** clicking either button SHALL NOT trigger a network request

#### Scenario: Logged-in user submits thumbs-up

- **GIVEN** the visitor is logged in
- **WHEN** they click thumbs-up below an AI answer with `query_id="q-7"`
- **THEN** the frontend SHALL `POST /qa-feedback` with body `{query_id: "q-7", vote: "up", comment: null}`
- **AND** on 201 response the up button SHALL change color to accent
- **AND** the text `已收到 ✓` SHALL appear next to the buttons

#### Scenario: Thumbs-down expands comment textarea

- **WHEN** a logged-in user clicks thumbs-down
- **THEN** an inline textarea SHALL expand below the buttons
- **AND** the `POST /qa-feedback` SHALL fire only after the user clicks the Send button (NOT immediately on thumbs-down click)

#### Scenario: User changes vote from up to down

- **GIVEN** the user previously clicked thumbs-up and saw the accent color
- **WHEN** they click thumbs-down and submit the comment textarea (empty or filled)
- **THEN** a new `POST /qa-feedback` SHALL fire with `vote: "down"`
- **AND** the up button SHALL revert to default color
- **AND** the down button SHALL become the accent color

### Requirement: QueryPage shows admin debug thumbs ratio

When the authenticated visitor's role is `admin` and at least one AI answer is present in the conversation, the QueryPage SHALL fetch `GET /qa-feedback/stats` once per session and render a small debug line near the top of the conversation area in the format `[admin] 7d thumbs: 8↑ 2↓ (80%)`. When `ratio` is `null` the line SHALL display `[admin] 7d thumbs: no data`. The debug line SHALL NOT render for non-admin users.

#### Scenario: Admin sees thumbs ratio debug line

- **GIVEN** a logged-in admin and a query result is rendered
- **WHEN** QueryPage mounts
- **THEN** exactly one `GET /qa-feedback/stats` request SHALL fire
- **AND** the debug line SHALL render with the format `[admin] 7d thumbs: 8↑ 2↓ (80%)`

#### Scenario: Non-admin does not see debug line

- **GIVEN** a logged-in user with role=`user`
- **WHEN** QueryPage renders a query result
- **THEN** no `GET /qa-feedback/stats` request SHALL fire
- **AND** the debug line SHALL NOT appear in the DOM
