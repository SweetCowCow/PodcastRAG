## MODIFIED Requirements

### Requirement: Admin schedule card exposes show-level actions

The admin `ScheduleTab` SHALL render a `selection checkbox`, the show metadata, a primary "立刻執行" / "Run Now" button, and a "⋯" overflow menu on each show card. The "立刻執行" button and the overflow menu's "編輯排程" / "Edit Schedule" and "移除排程" / "Remove Schedule" entries SHALL be shown only when the card's `schedule` field is not null. The selection checkbox, "更新節目集數" / "Refresh Episodes" overflow entry, and "刪除節目" / "Delete Show" overflow entry SHALL always be shown. The legacy in-card enable toggle, "Sync Episodes" button, "Edit Schedule" button, "Remove Schedule" button, and "Delete Show" button SHALL NOT be rendered as standalone card buttons.

#### Scenario: Card with schedule shows checkbox, primary button, and full overflow menu

- **WHEN** a show card is rendered and its `schedule` field is an object
- **THEN** the card SHALL display a selection checkbox, the show metadata, the "立刻執行" button, and a "⋯" overflow menu
- **AND** the overflow menu SHALL contain entries: "更新節目集數", "編輯排程", "移除排程", "刪除節目"

#### Scenario: Card without schedule hides schedule-only entries

- **WHEN** a show card is rendered and its `schedule` field is null
- **THEN** the card SHALL display the selection checkbox, the show metadata, and the "⋯" overflow menu
- **AND** the "立刻執行" button SHALL NOT be rendered
- **AND** the overflow menu SHALL contain entries: "更新節目集數", "刪除節目" only; "編輯排程" and "移除排程" SHALL NOT be rendered

#### Scenario: Legacy in-card toggle is removed

- **WHEN** any show card is rendered
- **THEN** the card SHALL NOT render the previous enable/disable toggle widget on the card body

---

### Requirement: Sync Episodes is non-destructive and requires no confirmation

The "更新節目集數" / "Refresh Episodes" action (accessed via the card's "⋯" overflow menu) SHALL call `POST /shows/{show_id}/sync` directly without showing a confirmation modal. While the request is in flight, the menu entry SHALL be disabled and the card SHALL show a loading indicator. On success, a toast or alert SHALL display the counts `added` and `updated` from the API response, and the card's `pending_count` and `last_transcribed_at` SHALL be refreshed via `GET /admin/schedules`.

#### Scenario: Refresh Episodes calls sync endpoint directly

- **WHEN** the user opens the "⋯" menu on a card and clicks "更新節目集數"
- **THEN** the frontend SHALL immediately call `POST /shows/{show_id}/sync` without opening a modal
- **AND** the menu entry SHALL be disabled until the request completes

#### Scenario: Refresh Episodes success shows counts

- **WHEN** `POST /shows/{show_id}/sync` returns HTTP 200 with `{added, updated, total}`
- **THEN** the frontend SHALL display a notification containing the `added` and `updated` counts
- **AND** the frontend SHALL re-fetch `GET /admin/schedules` to refresh the card

## ADDED Requirements

### Requirement: ScheduleTab supports row selection for batch operations

The admin `ScheduleTab` SHALL render a checkbox on each show card that toggles the show's membership in the current selection set. The selection set SHALL be transient client-side state (not persisted to the backend) and SHALL reset to empty on tab unmount or page reload. A "全選" / "Select All" master checkbox SHALL be rendered above the list; toggling it SHALL select or deselect every visible card. When the selection set is non-empty, a batch action bar SHALL appear at the top of the list containing: a "已選 N 個" / "N selected" counter, a "更新節目集數" / "Refresh Episodes" batch button, a "轉錄未完成集數" / "Transcribe Pending" batch button, and a "取消選取" / "Clear" button. When the selection set is empty, the batch action bar SHALL NOT be rendered.

#### Scenario: Selection bar hidden when nothing selected

- **WHEN** the `ScheduleTab` is rendered with no cards selected
- **THEN** the batch action bar SHALL NOT be visible
- **AND** the "全選" master checkbox SHALL be rendered in the unchecked state

#### Scenario: Selecting a card reveals the batch bar

- **WHEN** the user clicks the checkbox on one show card
- **THEN** the batch action bar SHALL appear at the top of the list
- **AND** the "已選 N 個" counter SHALL display "1"

#### Scenario: Select All toggles all visible cards

- **WHEN** there are 3 cards rendered and the user clicks the "全選" master checkbox while it is unchecked
- **THEN** all 3 cards SHALL become selected and the counter SHALL display "3"
- **WHEN** the user clicks "全選" again while it is checked
- **THEN** all 3 cards SHALL be deselected and the batch action bar SHALL hide

#### Scenario: Clear button empties the selection

- **WHEN** the batch action bar is visible and the user clicks "取消選取"
- **THEN** all card checkboxes SHALL become unchecked and the batch action bar SHALL hide

---

### Requirement: Batch Refresh Episodes fans out per selected show

The batch "更新節目集數" / "Refresh Episodes" button SHALL call `POST /shows/{show_id}/sync` once for each show in the selection set in parallel. The button SHALL NOT show a confirmation modal. While any request is in flight, the button SHALL be disabled and display a loading indicator. After all requests settle, a single notification SHALL summarise the result (e.g., total `added` count, total `updated` count, and any per-show errors). On completion, the frontend SHALL re-fetch `GET /admin/schedules` and SHALL preserve the current selection set.

#### Scenario: Batch refresh executes one request per selected show

- **WHEN** the user has selected 2 shows and clicks the batch "更新節目集數" button
- **THEN** the frontend SHALL send `POST /shows/{show_id}/sync` for each of the 2 shows
- **AND** the button SHALL remain disabled until all 2 requests have settled

#### Scenario: Batch refresh aggregates results

- **WHEN** all batch sync requests have settled with combined counts `added=5, updated=3` and zero errors
- **THEN** the notification SHALL display the aggregated `added` and `updated` totals
- **AND** the frontend SHALL re-fetch `GET /admin/schedules`

#### Scenario: Selection persists after batch refresh

- **WHEN** a batch refresh completes and the data is re-fetched
- **THEN** the previously selected cards SHALL remain checked

---

### Requirement: Batch Transcribe Pending requires confirmation and respects per-show max_episodes

The batch "轉錄未完成集數" / "Transcribe Pending" button SHALL open a confirmation modal before any network request is made. The modal SHALL display the count of selected shows and the message "即將對 N 個節目排入轉錄，會消耗 OpenAI 額度，是否繼續？" (or English equivalent), with "確認" / "Confirm" and "取消" / "Cancel" buttons. On "Confirm", the frontend SHALL call `POST /shows/{show_id}/transcribe-latest` once per selected show in parallel; the backend SHALL apply each show's own `schedule.max_episodes` value (existing behaviour of `transcribe-latest`). On "Cancel" or backdrop click, no network request SHALL be sent. While the requests are in flight, the button SHALL be disabled. After all requests settle, a single notification SHALL summarise total queued episodes and per-show errors.

#### Scenario: Confirmation modal opens before any request

- **WHEN** the user has selected 2 shows and clicks the batch "轉錄未完成集數" button
- **THEN** a confirmation modal SHALL appear stating "即將對 2 個節目排入轉錄"
- **AND** no `POST /shows/{show_id}/transcribe-latest` request SHALL be sent

#### Scenario: Cancel aborts the batch transcription

- **WHEN** the confirmation modal is open and the user clicks "取消"
- **THEN** the modal SHALL close and no network requests SHALL be sent

#### Scenario: Confirm fans out one request per selected show

- **WHEN** the user clicks "確認" with 2 shows selected
- **THEN** the frontend SHALL send `POST /shows/{show_id}/transcribe-latest` for each of the 2 shows
- **AND** each request SHALL omit the `max_episodes` query parameter so the backend uses each show's own `schedule.max_episodes` value

#### Scenario: Single-show "立刻執行" still skips the confirm modal

- **WHEN** the user clicks the per-card "立刻執行" button on a single card
- **THEN** the frontend SHALL call `POST /shows/{show_id}/transcribe-latest` directly without opening the batch confirmation modal

