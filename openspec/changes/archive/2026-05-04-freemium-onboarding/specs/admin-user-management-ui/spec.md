## ADDED Requirements

### Requirement: Admin Quota Requests sub-tab lists pending and processed quota_requests

The admin Users page SHALL include a secondary tab labelled `Quota 申請` (`zh`) / `Quota requests` (`en`) accessible at route `admin-quota-requests`. The tab SHALL display a table with columns: requester email, reason (truncated to 100 chars with hover tooltip for full text), requested_at (relative time, e.g. `3 小時前`), current `quota_remaining` of the requester (live, fetched alongside the listing), status filter chips (`pending` / `approved` / `rejected`, default `pending`), and per-row action area. The tab SHALL fetch from `GET /admin/quota-requests?status=<filter>`. A red badge SHALL appear on the tab label whenever the count of pending requests is greater than zero.

#### Scenario: Pending tab loads pending requests sorted by requested_at ASC

- **GIVEN** 3 pending quota_requests with `requested_at` 1h, 5h, and 12h ago
- **WHEN** an admin opens the Quota 申請 tab with default `pending` filter
- **THEN** the table SHALL render 3 rows, oldest first (12h, 5h, 1h)

#### Scenario: Status filter chip switches the listing

- **WHEN** the admin clicks the `approved` filter chip
- **THEN** the table SHALL refetch with `?status=approved` and render the corresponding rows

#### Scenario: Pending count badge appears on tab label

- **GIVEN** 3 pending quota_requests exist
- **WHEN** an admin views the Users page
- **THEN** the `Quota 申請` tab label SHALL display a red `3` badge

#### Scenario: Empty state when no pending requests

- **WHEN** there are zero pending quota_requests and the admin opens the tab with the default filter
- **THEN** the table SHALL show an empty state message `目前沒有 pending 的 quota 申請` (`zh`) / `No pending quota requests` (`en`)
- **AND** no red badge SHALL appear on the tab label

### Requirement: Admin can approve a quota request inline with an amount

For each row in `pending` status, the action area SHALL contain an inline numeric input (default 30, min 1, max 1000) and a primary button `核准 +N` (`zh`) / `Approve +N` (`en`) that updates its label live as the input value changes. Clicking the button SHALL `POST /admin/quota-requests/{id}/approve` with `{"amount": <input>}`. On HTTP 200 the row SHALL be removed from the pending listing (or rendered as approved if the filter is `approved`). On HTTP 409 (`already_processed`) the page SHALL show a toast `此申請已被處理` (`zh`) / `This request has been processed` (`en`) and refetch.

#### Scenario: Approve adds quota and removes row from pending

- **GIVEN** the admin is viewing the `pending` filter with 3 rows
- **WHEN** the admin sets the amount to 50 on row R and clicks `核准 +50`
- **THEN** the API SHALL be called with `{"amount": 50}`
- **AND** on success, row R SHALL no longer appear in the table
- **AND** the requester's `quota_remaining` SHALL increase by 50 (verifiable via the user management tab)

#### Scenario: Already-processed approve shows toast and refetches

- **GIVEN** another admin already approved row R in another browser
- **WHEN** the current admin clicks `核准 +30` on row R
- **THEN** the API SHALL return HTTP 409
- **AND** the page SHALL show a toast and refetch the listing
- **AND** row R SHALL no longer appear in the pending listing

### Requirement: Admin can reject a quota request with a note

For each row in `pending` status, the action area SHALL also contain a secondary `拒絕` (`zh`) / `Reject` (`en`) button. Clicking it SHALL open a small confirmation dialog with a `<textarea>` labelled `拒絕原因（會寄給使用者—未來功能）` (`zh`) / `Rejection reason (will be sent to user — future)` (`en`) requiring at least 1 character, and a confirm button. On confirm, the page SHALL `POST /admin/quota-requests/{id}/reject` with `{"note": "<textarea>"}`. On HTTP 200 the row SHALL be removed from the pending listing.

#### Scenario: Reject removes row from pending

- **GIVEN** a pending row R
- **WHEN** the admin clicks `拒絕`, types `理由不充分`, and confirms
- **THEN** `POST /admin/quota-requests/{R}/reject` SHALL be called with `{"note": "理由不充分"}`
- **AND** on success, row R SHALL no longer appear in the pending listing
- **AND** the requester's `quota_remaining` SHALL be unchanged

#### Scenario: Reject without note is blocked client-side

- **WHEN** the admin clicks confirm with an empty textarea
- **THEN** the dialog SHALL show a validation error and SHALL NOT call the API
