## MODIFIED Requirements

### Requirement: Admin schedule card exposes show-level actions

The admin `ScheduleTab` SHALL render five action buttons on each show card: "Sync Episodes", "Edit Schedule", "Run Now", "Remove Schedule", and "Delete Show". The "Edit Schedule", "Run Now", and "Remove Schedule" buttons SHALL be shown only when the card's `schedule` field is not null. The "Sync Episodes" and "Delete Show" buttons SHALL always be shown.

#### Scenario: Card with schedule shows all five buttons

- **WHEN** a show card is rendered and its `schedule` field is an object
- **THEN** the card SHALL display "Sync Episodes", "Edit Schedule", "Run Now", "Remove Schedule", and "Delete Show" buttons

#### Scenario: Card without schedule hides schedule-only buttons

- **WHEN** a show card is rendered and its `schedule` field is null
- **THEN** the card SHALL display "Sync Episodes" and "Delete Show" buttons only; "Edit Schedule", "Run Now", and "Remove Schedule" SHALL NOT be rendered

## ADDED Requirements

### Requirement: Edit Schedule opens a form modal and persists via PUT

The "Edit Schedule" button SHALL open a `FormModal` pre-populated with the card's current `schedule.frequency`, `schedule.run_time`, `schedule.whisper_model`, and `schedule.max_episodes` values. Submitting the form SHALL call `PUT /shows/{show_id}/schedule` with all four fields; on HTTP 200 response, the frontend SHALL close the modal and re-fetch `GET /admin/schedules`. Cancelling or closing the modal SHALL make no network request.

#### Scenario: Form is pre-populated with current values

- **WHEN** the user clicks "Edit Schedule" on a card whose schedule has `frequency=weekly, run_time=08:00, whisper_model=medium, max_episodes=3`
- **THEN** the modal SHALL display those exact values in the form inputs before the user makes any edits

#### Scenario: Submit triggers PUT and reloads list

- **WHEN** the user edits `max_episodes` from 3 to 7 and clicks the confirm button
- **THEN** the frontend SHALL call `PUT /shows/{show_id}/schedule` with a body that includes `max_episodes: 7`
- **AND** on HTTP 200 the modal SHALL close and the card SHALL re-render with the updated value

#### Scenario: Cancel aborts without side effects

- **WHEN** the edit modal is open and the user clicks cancel or the backdrop
- **THEN** the modal SHALL close and no `PUT /shows/{show_id}/schedule` request SHALL be sent

### Requirement: Run Now triggers transcribe-latest for a single show

The "Run Now" button SHALL call `POST /shows/{show_id}/transcribe-latest` directly without opening a confirmation modal. While the request is in flight, the button SHALL be disabled and show a loading indicator. On HTTP 202 response, the frontend SHALL display a notification containing the response's `queued` count and `synced.added` / `synced.updated` counts, and SHALL re-fetch `GET /admin/schedules` to refresh the card.

#### Scenario: Run Now calls transcribe-latest with no modal

- **WHEN** the user clicks "Run Now" on an enabled show card
- **THEN** the frontend SHALL immediately call `POST /shows/{show_id}/transcribe-latest` without opening a modal

#### Scenario: Button disabled during request

- **WHEN** the `POST /shows/{show_id}/transcribe-latest` request is in flight
- **THEN** the "Run Now" button on that card SHALL be disabled until the request completes

#### Scenario: Success notification includes counts

- **WHEN** `POST /shows/{show_id}/transcribe-latest` returns HTTP 202 with `{queued: 3, synced: {added: 1, updated: 0}}`
- **THEN** the frontend SHALL display a notification containing the values 3, 1, and 0

### Requirement: Sync All uses transcribe-latest across enabled shows

The "Sync All" button SHALL iterate over every show whose `schedule.enabled === true` and call `POST /shows/{show_id}/transcribe-latest` for each (in parallel via `Promise.all`). On completion the frontend SHALL display a notification containing the number of shows processed and SHALL re-fetch `GET /admin/schedules`. "Sync All" SHALL NOT call `POST /shows/{show_id}/transcribe-all`.

#### Scenario: Only enabled shows are processed

- **WHEN** there are 4 shows of which 2 have `schedule.enabled=true` and the user clicks "Sync All"
- **THEN** the frontend SHALL fire exactly 2 `POST /shows/{show_id}/transcribe-latest` requests (one per enabled show)

#### Scenario: Disabled or missing schedules are skipped

- **WHEN** a show's `schedule` is null or `schedule.enabled=false` and the user clicks "Sync All"
- **THEN** no request SHALL be made for that show

## ADDED Requirements

### Requirement: FormModal shared component

The `Shared.jsx` module SHALL export a `FormModal` React component with props `{ open, title, children, confirmLabel, cancelLabel, onConfirm, onCancel, submitDisabled }`. When `open` is false, the component SHALL render nothing. When `open` is true, the component SHALL render a full-viewport backdrop and a centered card containing the title, the `children` slot for arbitrary form content, a primary confirm button (disabled when `submitDisabled` is true), and a ghost cancel button. Clicking the backdrop SHALL invoke `onCancel`. `FormModal` SHALL style the confirm button as `primary` (non-destructive), distinguishing it from `ConfirmModal` which uses `danger`.

#### Scenario: FormModal hides when open is false

- **WHEN** `FormModal` is rendered with `open={false}`
- **THEN** the component SHALL return null / render no DOM

#### Scenario: FormModal renders children in the body

- **WHEN** `FormModal` is rendered with `open={true}` and `children` containing form inputs
- **THEN** those inputs SHALL appear between the title and the action buttons

#### Scenario: Submit button respects submitDisabled

- **WHEN** `FormModal` is rendered with `open={true}` and `submitDisabled={true}`
- **THEN** the confirm button SHALL be rendered in a disabled state and clicking it SHALL NOT call `onConfirm`
