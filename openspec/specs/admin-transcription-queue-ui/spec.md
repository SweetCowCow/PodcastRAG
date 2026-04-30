# admin-transcription-queue-ui Specification

## Purpose

TBD - created by archiving change 'transcription-queue-and-schedule-ui'. Update Purpose after archive.

## Requirements

### Requirement: Admin page exposes a Transcription Queue tab

The admin page SHALL expose a "轉錄序列" (zh) / "Transcription Queue" (en) tab as the 6th admin tab, positioned after the Schedule tab and before the External API Status tab. The tab SHALL be reachable at route `admin-queue` (page state value). The tab SHALL display queue rows fetched from `GET /admin/queue` grouped into three sub-tabs by status:

| Sub-tab key | Label (zh) | Label (en) | Statuses included |
| ----------- | ---------- | ---------- | ----------------- |
| `active`    | 進行中     | Active     | pending, running  |
| `completed` | 已完成     | Completed  | completed         |
| `closed`    | 已結束     | Closed     | failed, cancelled |

Each sub-tab label SHALL include a count badge showing the total rows in that sub-tab (sum of constituent statuses). The active sub-tab indicator SHALL use `TOKEN.accent` for the underline/highlight; inactive sub-tabs SHALL use `TOKEN.textSecondary`.

Within each sub-tab, rows SHALL be grouped by status into sections when the sub-tab contains more than one status:

- `active`: two sections, "排隊中（可拖動排序）" / "Pending (drag to reorder)" on desktop, "排隊中" / "Pending" on mobile (drag is unavailable on mobile, see below); and "執行中" / "Running"
- `closed`: two sections, "失敗" / "Failed" and "已取消" / "Cancelled"
- `completed`: a single flat list with no section header

Each row SHALL display the episode title, the show name, a status badge, the relevant timestamps (`enqueued_at`, `started_at`, `finished_at` when present), the `error_message` for failed/cancelled rows, and the `celery_task_id` (collapsible/folded by default for debug).

When `isMobile` is `false` (desktop), each row SHALL render its content in a single horizontal flex row exactly as today (drag handle on the left, metadata in the middle, action buttons on the right). When `isMobile` is `true`, each row SHALL render its content in a vertical stack (metadata first, then action buttons wrapped onto one or more rows below). The drag handle (`⋮⋮`) SHALL NOT be rendered on mobile.

The active sub-tab SHALL default to `active` on first mount. Switching sub-tabs SHALL be local UI state and SHALL NOT trigger an additional `GET /admin/queue` call (the existing 5-second polling already covers all statuses in one response).

The tab SHALL poll `GET /admin/queue` and `GET /admin/settings` every 5 seconds while mounted regardless of which sub-tab is active; the polling SHALL stop when the tab unmounts or the user navigates away.

All existing per-row actions SHALL be preserved unchanged: "取消" / "Cancel" for pending, "強制取消" / "Force Cancel" for running (with confirmation), "重試" / "Retry" and "忽略" / "Ignore" for failed rows, "取消忽略" / "Unignore" for ignored rows. Drag-to-reorder for pending rows SHALL be preserved on desktop but SHALL be replaced with up/down arrow buttons on mobile (see "Pending row reorder" requirement below).

#### Scenario: Tab renders three sub-tabs grouping five statuses

- **GIVEN** the queue contains rows with statuses pending, running, completed, failed, cancelled
- **WHEN** the user navigates to the Transcription Queue tab
- **THEN** the tab SHALL render exactly three sub-tab buttons labelled "進行中", "已完成", "已結束" (zh) or "Active", "Completed", "Closed" (en)
- **AND** each sub-tab label SHALL include a count badge showing the total rows for the statuses it covers
- **AND** the `active` sub-tab SHALL be selected by default

#### Scenario: Active sub-tab shows pending and running with section headers

- **GIVEN** the queue has 3 pending rows and 1 running row, desktop viewport
- **WHEN** the user views the `active` sub-tab
- **THEN** the sub-tab SHALL render two sections: "排隊中（可拖動排序）" with 3 rows and "執行中" with 1 row
- **AND** pending rows SHALL remain draggable and running row SHALL render the "強制取消" button

#### Scenario: Active sub-tab on mobile

- **GIVEN** the queue has 3 pending rows and 1 running row, mobile viewport
- **WHEN** the user views the `active` sub-tab
- **THEN** the pending section heading SHALL read "排隊中" / "Pending" (without "(drag to reorder)")
- **AND** each pending row SHALL render in a vertical stack with metadata stacked above wrapped action buttons
- **AND** no drag handle (⋮⋮) SHALL appear

#### Scenario: Closed sub-tab shows failed and cancelled with section headers

- **GIVEN** the queue has 2 failed rows and 1 cancelled row
- **WHEN** the user views the `closed` sub-tab
- **THEN** the sub-tab SHALL render two sections: "失敗" with 2 rows and "已取消" with 1 row
- **AND** failed rows SHALL render "重試" / "忽略" buttons and cancelled rows SHALL render no action buttons

#### Scenario: Completed sub-tab is a flat list

- **GIVEN** the queue has 5 completed rows
- **WHEN** the user views the `completed` sub-tab
- **THEN** the sub-tab SHALL render the 5 rows as a flat list with no section header

#### Scenario: Switching sub-tabs does not trigger network request

- **GIVEN** the Transcription Queue tab is mounted on the `active` sub-tab
- **WHEN** the user clicks the `completed` sub-tab
- **THEN** no additional `GET /admin/queue` request SHALL be sent solely as a result of the click
- **AND** the next scheduled 5-second poll SHALL still execute normally

#### Scenario: Empty sub-tab shows empty placeholder

- **GIVEN** the queue contains zero failed and zero cancelled rows
- **WHEN** the user views the `closed` sub-tab
- **THEN** each section within the sub-tab SHALL render the "空" / "Empty" placeholder
- **AND** the count badge in the `closed` sub-tab label SHALL show 0

#### Scenario: Polling refreshes data every 5 seconds

- **GIVEN** the Transcription Queue tab is mounted
- **WHEN** 5 seconds elapse
- **THEN** the frontend SHALL re-call `GET /admin/queue` and `GET /admin/settings`
- **AND** when the tab unmounts, the polling interval SHALL be cleared


<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
code:
  - index.html
  - src/Shared.jsx
  - src/TranscriptPage.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/PodcastSelect.jsx
  - src/App.jsx
  - src/QueryPage.jsx
  - src/QueueTab.jsx
  - src/AdminPage.jsx
-->

---
### Requirement: Pending rows expose Cancel button; Running rows expose Force Cancel button

For each pending row, the tab SHALL render a "取消" / "Cancel" button. Clicking it SHALL call `POST /admin/queue/{id}/cancel` (no `force` parameter) and on HTTP 200 SHALL refresh the queue list.

For each running row, the tab SHALL render a red "強制取消" / "Force Cancel" button. Clicking it SHALL open a confirmation dialog with text "確定要強制取消正在執行的轉錄嗎？此動作會中止 Whisper 呼叫且不可復原" (zh) / "Confirm force-cancel? This will abort the running Whisper call and cannot be undone." (en) and two buttons "確認" / "Confirm" and "取消" / "Cancel". On Confirm the frontend SHALL call `POST /admin/queue/{id}/cancel?force=true` and on HTTP 200 SHALL refresh the queue list. The Confirm button SHALL be disabled while the request is in flight.

The pending Cancel button SHALL NOT appear on running rows; the running Force Cancel button SHALL NOT appear on pending rows.

#### Scenario: Cancel pending row

- **GIVEN** a pending row is visible
- **WHEN** the user clicks "Cancel"
- **THEN** the frontend SHALL POST to `/admin/queue/{id}/cancel` without query parameters
- **AND** on HTTP 200 the queue list SHALL re-render with the row appearing in the cancelled section

#### Scenario: Force-cancel running row requires confirmation

- **GIVEN** a running row is visible
- **WHEN** the user clicks "Force Cancel"
- **THEN** a confirmation dialog SHALL appear before any network request is made
- **WHEN** the user clicks "Confirm" in the dialog
- **THEN** the frontend SHALL POST to `/admin/queue/{id}/cancel?force=true`
- **AND** on HTTP 200 the row SHALL move to the cancelled section on the next render

#### Scenario: Confirmation dialog Cancel aborts without request

- **GIVEN** the force-cancel confirmation dialog is open
- **WHEN** the user clicks "Cancel" or dismisses the dialog
- **THEN** no network request SHALL be sent and the row SHALL remain in running status


<!-- @trace
source: transcription-queue-and-schedule-ui
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - backend/app/schemas/queue.py
  - src/Shared.jsx
  - backend/app/api/queue.py
  - src/QueueTab.jsx
  - src/AdminPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
tests:
  - backend/tests/test_queue_reorder.py
-->

---
### Requirement: Failed rows expose Retry and Ignore; Ignored rows expose Unignore

For each failed row that is NOT ignored, the tab SHALL render a "重試" / "Retry" button and an "忽略" / "Ignore" button. Retry SHALL call `POST /episodes/{episode_id}/transcribe` (re-enqueue the episode). Ignore SHALL call `POST /admin/queue/{id}/ignore`.

For each row with `ignored=true`, the tab SHALL render the row with a muted/grayed style and SHALL render a "取消忽略" / "Unignore" button instead of Retry/Ignore. Unignore SHALL call `POST /admin/queue/{id}/unignore`.

#### Scenario: Retry failed row re-enqueues

- **GIVEN** a failed row with `ignored=false` is visible
- **WHEN** the user clicks "Retry"
- **THEN** the frontend SHALL POST to `/episodes/{episode_id}/transcribe`
- **AND** on HTTP 202 the row SHALL move to pending on the next refresh

#### Scenario: Ignore failed row marks it ignored

- **GIVEN** a failed row with `ignored=false` is visible
- **WHEN** the user clicks "Ignore"
- **THEN** the frontend SHALL POST to `/admin/queue/{id}/ignore`
- **AND** on HTTP 200 the row SHALL render with muted style and the buttons SHALL switch to "Unignore"


<!-- @trace
source: transcription-queue-and-schedule-ui
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - backend/app/schemas/queue.py
  - src/Shared.jsx
  - backend/app/api/queue.py
  - src/QueueTab.jsx
  - src/AdminPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
tests:
  - backend/tests/test_queue_reorder.py
-->

---
### Requirement: Tab header exposes max_concurrent_transcriptions input

The Transcription Queue tab SHALL display a number input labeled "並行上限" (zh) / "Max Concurrent" (en) at the top of the tab. The input SHALL bind to `max_concurrent_transcriptions` from `GET /admin/settings`. The input SHALL accept integers 1–3 inclusive; values outside this range SHALL show a helper text "上限 3，受 worker concurrency 限制" (zh) / "Max 3, limited by worker concurrency" (en) in a warning color.

The input's `onChange` SHALL update local state immediately and SHALL trigger a debounced `PUT /admin/settings` after 500 milliseconds of inactivity. On HTTP 422 (out-of-range) the frontend SHALL revert the local state to the server value and SHALL display the backend error message.

#### Scenario: Setting concurrency to 2 calls PUT after debounce

- **GIVEN** current setting is `max_concurrent_transcriptions=1`
- **WHEN** the user types `2` and waits 500ms
- **THEN** the frontend SHALL PUT to `/admin/settings` with body `{"max_concurrent_transcriptions": 2}`
- **AND** on HTTP 200 the input SHALL show value `2`

#### Scenario: Setting concurrency to 5 shows warning

- **GIVEN** the input
- **WHEN** the user types `5`
- **THEN** the helper text "Max 3, limited by worker concurrency" SHALL appear in warning color
- **AND** the PUT call SHALL still fire (backend rejects with 422)
- **AND** on the 422 response the local state SHALL revert to the previous valid value


<!-- @trace
source: transcription-queue-and-schedule-ui
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - backend/app/schemas/queue.py
  - src/Shared.jsx
  - backend/app/api/queue.py
  - src/QueueTab.jsx
  - src/AdminPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
tests:
  - backend/tests/test_queue_reorder.py
-->

---
### Requirement: Pending rows are draggable to reorder

Pending rows in the Transcription Queue tab SHALL be draggable using HTML5 native drag-and-drop. Each pending row SHALL have `draggable={true}` and SHALL set the queue row id in `dataTransfer` on `dragstart`. Pending rows SHALL accept drops via `onDragOver` (with `preventDefault`) and `onDrop`. Dropping row A onto row B SHALL trigger a `PATCH /admin/queue/{A.id}/position` with body `{"position": B.position}`.

The frontend SHALL apply the new ordering optimistically immediately on drop. On HTTP 200 the polling refresh SHALL confirm the order. On HTTP error (4xx / 5xx) the frontend SHALL revert to the previous ordering and SHALL display a toast/inline error message.

While a drag is in flight (between drop and HTTP response), the pending list SHALL refuse new drag operations to avoid race conditions.

Drag MUST be confined to within the pending section — dropping onto a row in any other status section SHALL be ignored.

#### Scenario: Drag pending row B onto row A reorders

- **GIVEN** pending rows are `[A(pos=10), B(pos=11), C(pos=12)]`
- **WHEN** the user drags row B onto row A
- **THEN** the frontend SHALL PATCH `/admin/queue/B.id/position` with `{"position": 10}`
- **AND** on HTTP 200 the next render SHALL show order `[B, A, C]`

#### Scenario: Drop on running row is ignored

- **WHEN** the user drags a pending row and drops onto a running row
- **THEN** no PATCH request SHALL be sent
- **AND** the pending list SHALL retain its previous order

#### Scenario: PATCH error reverts order

- **GIVEN** pending rows are `[A, B, C]`
- **WHEN** the user drops B onto A and the PATCH returns HTTP 409 (e.g. row no longer pending)
- **THEN** the frontend SHALL revert to `[A, B, C]`
- **AND** SHALL display an error message

<!-- @trace
source: transcription-queue-and-schedule-ui
updated: 2026-04-28
code:
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - backend/app/schemas/queue.py
  - src/Shared.jsx
  - backend/app/api/queue.py
  - src/QueueTab.jsx
  - src/AdminPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
tests:
  - backend/tests/test_queue_reorder.py
-->

---
### Requirement: Pending row reorder uses arrow buttons on mobile

When `isMobile` is `true`, each pending queue row SHALL render two icon buttons in its action area: an "↑" (move up) button and a "↓" (move down) button, in addition to the existing "Cancel" button. The "↑" button SHALL be disabled on the first pending row; the "↓" button SHALL be disabled on the last pending row. Clicking "↑" SHALL call `PATCH /admin/queue/{row_id}/position` with body `{position: targetPosition}` where `targetPosition` is the position value of the row immediately above in the current pending order. Clicking "↓" SHALL behave symmetrically with the row immediately below.

While a reorder request is in flight, both arrow buttons on all pending rows SHALL be disabled (mirrors the existing `dragInFlight` flag used for desktop drag). On HTTP 200 success the frontend SHALL re-fetch `GET /admin/queue` and clear the optimistic override. On error the frontend SHALL display the error message in the row's action error area (same path as existing `actionError[row_id]`).

When `isMobile` is `false`, the arrow buttons SHALL NOT be rendered; the existing HTML5 drag-and-drop UI SHALL remain unchanged.

#### Scenario: Up arrow disabled on first pending row

- **GIVEN** mobile viewport, pending list has 3 rows ordered A, B, C
- **WHEN** the user views row A's action buttons
- **THEN** the "↑" button SHALL be disabled
- **AND** the "↓" button SHALL be enabled

#### Scenario: Down arrow disabled on last pending row

- **GIVEN** mobile viewport, pending list has 3 rows ordered A, B, C
- **WHEN** the user views row C's action buttons
- **THEN** the "↓" button SHALL be disabled
- **AND** the "↑" button SHALL be enabled

#### Scenario: Up arrow swaps with row above

- **GIVEN** mobile viewport, pending list ordered A (position 0), B (position 1), C (position 2)
- **WHEN** the user taps "↑" on row B
- **THEN** the frontend SHALL call `PATCH /admin/queue/{B_id}/position` with body `{position: 0}`
- **AND** on HTTP 200 the list SHALL re-render in order B, A, C (after refetch)

#### Scenario: Reorder in flight disables all arrow buttons

- **GIVEN** mobile viewport, a reorder request is currently pending
- **WHEN** the user views any pending row
- **THEN** both ↑ and ↓ buttons on every pending row SHALL be disabled until the request completes

#### Scenario: Reorder failure shows error in row

- **GIVEN** mobile viewport, the user taps "↓" on a pending row
- **WHEN** the backend returns HTTP 4xx with detail "Some error"
- **THEN** the row SHALL display "Some error" in its action error area
- **AND** the pending list ordering SHALL remain unchanged

#### Scenario: Desktop layout unaffected

- **GIVEN** desktop viewport
- **WHEN** a pending row is rendered
- **THEN** the row SHALL render the drag handle (⋮⋮) and SHALL NOT render arrow buttons
- **AND** drag-to-reorder SHALL function exactly as today

<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
-->

<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
code:
  - index.html
  - src/Shared.jsx
  - src/TranscriptPage.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/PodcastSelect.jsx
  - src/App.jsx
  - src/QueryPage.jsx
  - src/QueueTab.jsx
  - src/AdminPage.jsx
-->