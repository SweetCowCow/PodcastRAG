## ADDED Requirements

### Requirement: Admin schedule card exposes show-level actions

The admin `ScheduleTab` SHALL render three action buttons on each show card: "Sync Episodes", "Remove Schedule", and "Delete Show". The "Remove Schedule" button SHALL be shown only when the card's `schedule` field is not null. The "Sync Episodes" and "Delete Show" buttons SHALL always be shown.

#### Scenario: Card with schedule shows all three buttons

- **WHEN** a show card is rendered and its `schedule` field is an object
- **THEN** the card SHALL display "Sync Episodes", "Remove Schedule", and "Delete Show" buttons

#### Scenario: Card without schedule hides Remove Schedule

- **WHEN** a show card is rendered and its `schedule` field is null
- **THEN** the card SHALL display "Sync Episodes" and "Delete Show" buttons only; "Remove Schedule" SHALL NOT be rendered

### Requirement: Destructive actions require explicit confirmation

Destructive actions ("Delete Show" and "Remove Schedule") SHALL open a confirmation modal before any network request is made. The modal SHALL display the target's name (show title for delete, show title for remove schedule), a description of what will be deleted, and two buttons: "Confirm Delete" and "Cancel". The destructive action SHALL execute only after the user clicks "Confirm Delete". Clicking "Cancel" or closing the modal SHALL abort the action with no side effects.

#### Scenario: Delete Show opens confirm modal

- **WHEN** the user clicks "Delete Show" on a card
- **THEN** a confirmation modal SHALL appear naming the show and stating that episodes, transcripts, and schedule will be cascaded
- **AND** no `DELETE /shows/{id}` request SHALL be sent until the user clicks "Confirm Delete"

#### Scenario: Cancel aborts without side effects

- **WHEN** the confirmation modal is open and the user clicks "Cancel"
- **THEN** the modal SHALL close and no network request SHALL be sent

#### Scenario: Confirm Delete triggers DELETE request

- **WHEN** the confirmation modal is open and the user clicks "Confirm Delete" for a show
- **THEN** the frontend SHALL call `DELETE /shows/{show_id}`
- **AND** on HTTP 204 response, the frontend SHALL re-fetch `GET /admin/schedules` and remove the card from the list

### Requirement: Remove Schedule deletes only the schedule row

The "Remove Schedule" action SHALL call `DELETE /shows/{show_id}/schedule` after confirmation. On success the show SHALL remain in the list, but its card SHALL re-render with `schedule: null` (showing the "未設定" badge and hiding the "Remove Schedule" button).

#### Scenario: Remove Schedule succeeds

- **WHEN** the user confirms "Remove Schedule" for a show with a schedule
- **THEN** the frontend SHALL call `DELETE /shows/{show_id}/schedule`
- **AND** on HTTP 204 response, the card SHALL re-render with the schedule removed and the show SHALL remain in the list

### Requirement: Sync Episodes is non-destructive and requires no confirmation

The "Sync Episodes" action SHALL call `POST /shows/{show_id}/sync` directly without showing a confirmation modal. While the request is in flight, the button SHALL be disabled and show a loading indicator. On success, a toast or alert SHALL display the counts `added` and `updated` from the API response, and the card's `pending_count` and `last_transcribed_at` SHALL be refreshed via `GET /admin/schedules`.

#### Scenario: Sync Episodes calls sync endpoint directly

- **WHEN** the user clicks "Sync Episodes" on a card
- **THEN** the frontend SHALL immediately call `POST /shows/{show_id}/sync` without opening a modal
- **AND** the button SHALL be disabled until the request completes

#### Scenario: Sync success shows counts

- **WHEN** `POST /shows/{show_id}/sync` returns HTTP 200 with `{added, updated, total}`
- **THEN** the frontend SHALL display a notification containing the `added` and `updated` counts
- **AND** the frontend SHALL re-fetch `GET /admin/schedules` to refresh the card

### Requirement: PodcastSelect remains read-only

The public-facing `PodcastSelect` page SHALL NOT render any create, edit, or delete controls for shows. Management actions SHALL be accessible only via the admin area.

#### Scenario: PodcastSelect has no management buttons

- **WHEN** the `PodcastSelect` page is rendered for any user
- **THEN** the page SHALL NOT display any "Add Show", "Edit Show", "Delete Show", or equivalent buttons
