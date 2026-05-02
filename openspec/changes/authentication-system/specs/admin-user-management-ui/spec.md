## ADDED Requirements

### Requirement: Admin user management tab lists all users

The frontend admin section SHALL provide a "Users" tab (route `admin-users`) accessible only when the current user has `role='admin'`. The tab SHALL render a table listing all users from `GET /admin/users` with columns: Avatar, Name, Email, Role, Status, Provider, Created (date), Last login (date or em-dash if null), Total queries, Quota remaining, Notes (truncated), and Actions.

#### Scenario: Admin opens users tab

- **WHEN** an authenticated admin navigates to the Users tab
- **THEN** the table SHALL render one row per user returned by `GET /admin/users`
- **AND** every column listed above SHALL be present in the table header

#### Scenario: Non-admin cannot access users tab

- **WHEN** an authenticated user with `role='member'` navigates to the URL hash for the Users tab
- **THEN** the tab content SHALL NOT render and the user SHALL be redirected to a non-admin page
- **AND** the `GET /admin/users` request SHALL NOT be issued by the frontend

### Requirement: Admin can edit role, status, and notes per user

Each row in the users table SHALL provide an "Edit" affordance that opens a modal allowing the admin to change `role` (admin / member), `status` (active / pending / disabled), and `notes` (free-text up to 500 characters). Saving SHALL call `PATCH /admin/users/{id}` with only the changed fields.

#### Scenario: Edit modal preloads current values

- **WHEN** the admin clicks Edit on a row whose user has `role='member'`, `status='active'`, `notes='trial user'`
- **THEN** the modal SHALL show the role selector preset to `member`, status preset to `active`, and the notes textarea containing `trial user`

#### Scenario: Save sends only changed fields

- **WHEN** the admin opens Edit and changes only `status` from `active` to `disabled`
- **THEN** the `PATCH /admin/users/{id}` request body SHALL be `{"status": "disabled"}` (no `role`, no `notes`)

### Requirement: Admin can top up a user's remaining quota

Each row SHALL provide a "Top up" action that opens a small modal with a numeric input (default 100, accepting positive or negative integers). Submitting SHALL call `PATCH /admin/users/{id}/quota` with body `{"delta": <value>}` and SHALL update the displayed `Quota remaining` cell with the response value.

#### Scenario: Top-up modal accepts positive delta

- **WHEN** the admin enters `50` in the top-up input and submits, while the target user has `quota_remaining=20`
- **THEN** the request SHALL be `PATCH /admin/users/{id}/quota` with body `{"delta": 50}`
- **AND** upon a successful response containing `{"quota_remaining": 70}`, the table cell SHALL update to `70`

#### Scenario: Top-up modal accepts negative delta

- **WHEN** the admin enters `-10` and submits
- **THEN** the request body SHALL be `{"delta": -10}` (negative integer permitted)

### Requirement: Admin can delete a user

Each row SHALL provide a Delete action that requires a confirmation dialog before calling `DELETE /admin/users/{id}`. After successful deletion, the row SHALL be removed from the table without a full page reload.

#### Scenario: Delete requires confirmation

- **WHEN** the admin clicks Delete on a row
- **THEN** a confirmation dialog SHALL appear displaying the target user's email
- **AND** the `DELETE /admin/users/{id}` request SHALL only be issued if the admin confirms

#### Scenario: Self-deletion is blocked at UI

- **WHEN** the admin clicks Delete on the row representing their own currently-logged-in user
- **THEN** the Delete action SHALL be disabled or a tooltip SHALL explain "Cannot delete your own account"

### Requirement: Frontend displays current user info and remaining quota

The top navigation bar SHALL display the authenticated user's avatar, name, and remaining quota (e.g., "Remaining: 87"). When `quota_remaining` is 0, the indicator SHALL be styled in a danger color and the query input on `QueryPage` SHALL be disabled with a bilingual hint ("查詢額度已用完" / "Quota exhausted").

#### Scenario: Quota indicator updates after a query

- **WHEN** the query API responds with a payload that includes the new `quota_remaining`
- **THEN** the top-nav indicator SHALL re-render with the new value within the same render pass

#### Scenario: Logged-out top-nav shows Sign in button

- **WHEN** no authenticated session exists
- **THEN** the top-nav SHALL show a "Sign in with Google" button instead of avatar/name/quota
- **AND** clicking the button SHALL navigate the browser to `GET /auth/google/start` on the backend

### Requirement: Bilingual labels in user management UI

All user-facing strings in the Users tab and current-user nav widget SHALL provide both Traditional Chinese and English variants, switched by the existing `lang` prop.

#### Scenario: Language toggle switches table headers

- **WHEN** the active language is changed from English to Traditional Chinese
- **THEN** the column headers SHALL update from "Avatar / Name / Email / Role / Status / Provider / Created / Last login / Total queries / Quota remaining / Notes / Actions" to the corresponding Traditional Chinese labels
