## ADDED Requirements

### Requirement: Public PodcastSelect empty-state routes admins to admin show management

When the public `PodcastSelect` page renders with zero shows available, the empty-state SHALL render different call-to-action content based on the current user's role:

- If the current user has `role='admin'` and `status='active'`: a primary button labelled "前往後台管理節目" / "Go to admin show management" that, when clicked, sets the application page state to `'admin-rag'` (the admin tab containing show CRUD).
- If the current user is unauthenticated or has `role='member'`: a static bilingual hint reading "目前尚無節目，請聯絡管理員加入節目" / "No shows yet — please contact an administrator to add one". No call-to-action button SHALL be rendered.

The empty-state SHALL NOT render a `POST /shows` form or a button that triggers any direct call to `POST /shows`.

#### Scenario: Admin sees redirect button on empty PodcastSelect

- **GIVEN** the current user has `role='admin'`, `status='active'`, and `GET /shows` returns an empty list
- **WHEN** the user opens the PodcastSelect page
- **THEN** the empty-state SHALL render a button labelled "前往後台管理節目" or "Go to admin show management"
- **AND** clicking the button SHALL set the page state to `'admin-rag'`

#### Scenario: Member sees contact-admin hint on empty PodcastSelect

- **GIVEN** the current user has `role='member'` and `GET /shows` returns an empty list
- **WHEN** the user opens the PodcastSelect page
- **THEN** the empty-state SHALL render the bilingual hint described above
- **AND** no call-to-action button SHALL render

#### Scenario: Unauthenticated visitor sees contact-admin hint

- **GIVEN** no current user (unauthenticated session) and `GET /shows` returns an empty list
- **WHEN** the visitor opens the PodcastSelect page
- **THEN** the empty-state SHALL render the bilingual hint
- **AND** no call-to-action button SHALL render

#### Scenario: Empty-state never triggers POST /shows

- **WHEN** the empty-state is rendered for any role
- **THEN** no element in the empty-state region SHALL invoke `fetch` or `apiFetch` with method `POST` and path `/shows`
