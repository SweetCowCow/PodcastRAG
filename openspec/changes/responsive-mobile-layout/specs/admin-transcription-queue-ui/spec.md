## MODIFIED Requirements

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

## ADDED Requirements

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

