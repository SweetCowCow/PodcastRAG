## MODIFIED Requirements

### Requirement: Destructive actions require explicit confirmation

Destructive actions ("Delete Show" and "Remove Schedule") SHALL open a confirmation modal before any network request is made. The modal SHALL display the target's name (show title for delete, show title for remove schedule), a description of what will be deleted, and two buttons: "Confirm Delete" and "Cancel". The destructive action SHALL execute only after the user clicks "Confirm Delete". Clicking "Cancel" or closing the modal SHALL abort the action with no side effects.

When the user clicks "Delete Show", the frontend SHALL — before opening the confirmation modal — call `GET /admin/queue` to count queue rows belonging to the target show grouped by `status`. The confirmation modal SHALL include a cascade-impact line of the form "將同時取消 N 筆排隊中、M 筆執行中的轉錄任務" (zh) / "Will cancel N pending and M running transcription jobs" (en) where N is the count of `pending` rows for the show and M is the count of `running` rows for the show. If both N and M are 0, the cascade-impact line SHALL be omitted. The cascade fetch SHALL NOT be cached — the frontend SHALL re-fetch each time the user clicks Delete Show.

#### Scenario: Delete Show opens confirm modal with cascade count

- **GIVEN** the target show has 3 pending and 1 running queue row
- **WHEN** the user clicks "Delete Show" on a card
- **THEN** the frontend SHALL fetch `GET /admin/queue` first
- **AND** a confirmation modal SHALL appear naming the show, stating that episodes/transcripts/schedule cascade, AND showing "Will cancel 3 pending and 1 running transcription jobs"
- **AND** no `DELETE /shows/{id}` request SHALL be sent until the user clicks "Confirm Delete"

#### Scenario: Delete Show with no queue rows omits cascade line

- **GIVEN** the target show has 0 pending and 0 running queue rows
- **WHEN** the user clicks "Delete Show"
- **THEN** the confirm modal SHALL NOT include the cascade-impact line
- **AND** the modal SHALL otherwise render normally

#### Scenario: Cancel aborts without side effects

- **WHEN** the confirmation modal is open and the user clicks "Cancel"
- **THEN** the modal SHALL close and no network request SHALL be sent

#### Scenario: Confirm Delete triggers DELETE request

- **WHEN** the confirmation modal is open and the user clicks "Confirm Delete" for a show
- **THEN** the frontend SHALL call `DELETE /shows/{show_id}`
- **AND** on HTTP 204 response, the frontend SHALL re-fetch `GET /admin/schedules` and remove the card from the list

## ADDED Requirements

### Requirement: Schedule modal exposes max_episodes_per_run input

The schedule edit/create modal SHALL include a number input labeled "每次最多轉錄集數" (zh) / "Max Episodes Per Run" (en) bound to the schedule's `max_episodes_per_run` field. The input SHALL accept integers ≥ 1 (matching backend `Field(..., ge=1)`). When creating a new schedule, the input SHALL default to 5. When editing, the input SHALL default to the schedule's current value.

The form SHALL submit `max_episodes_per_run` along with other fields when the user clicks Save.

#### Scenario: Editing existing schedule pre-fills max_episodes_per_run

- **GIVEN** a schedule with `max_episodes_per_run=10`
- **WHEN** the user opens the edit modal
- **THEN** the "Max Episodes Per Run" input SHALL show value 10

#### Scenario: New schedule defaults to 5

- **GIVEN** a show without a schedule
- **WHEN** the user opens "Add Schedule" modal
- **THEN** the "Max Episodes Per Run" input SHALL show default value 5

#### Scenario: Saving submits max_episodes_per_run

- **GIVEN** the modal is open and the user has entered max_episodes_per_run=8
- **WHEN** the user clicks Save
- **THEN** the request body SHALL include `"max_episodes_per_run": 8`

### Requirement: Schedule card displays last refresh status

Each schedule card SHALL display the last refresh state in a footer area showing `last_refresh_at` (relative time, e.g. "3 分鐘前刷新" / "Refreshed 3 minutes ago"), `last_refresh_status` (one of `success`, `failed`, `pending`), and on hover/expand the `last_refresh_message`.

The footer SHALL color-code by status: green ✓ for `success`, red ✗ for `failed`, gray for `pending` or null. When `last_refresh_at` is null (no refresh has run), the footer SHALL show "尚未刷新" (zh) / "Not yet refreshed" (en) in gray with no time.

The schedule modal SHALL also include a read-only block displaying the same three fields (`last_refresh_at`, `last_refresh_status`, `last_refresh_message`) when editing an existing schedule.

#### Scenario: Successful refresh shows green check

- **GIVEN** a schedule with `last_refresh_status=success` and `last_refresh_at` 3 minutes ago
- **WHEN** the card renders
- **THEN** the footer SHALL show "✓ 3 分鐘前刷新" / "✓ Refreshed 3 minutes ago" in green color

#### Scenario: Failed refresh shows red cross with hoverable message

- **GIVEN** a schedule with `last_refresh_status=failed` and `last_refresh_message="RSS timeout"`
- **WHEN** the card renders
- **THEN** the footer SHALL show "✗" in red with relative time
- **AND** hovering or expanding SHALL reveal "RSS timeout"

#### Scenario: No refresh history shows gray placeholder

- **GIVEN** a schedule with `last_refresh_at=null`
- **WHEN** the card renders
- **THEN** the footer SHALL show "尚未刷新" / "Not yet refreshed" in gray with no time
