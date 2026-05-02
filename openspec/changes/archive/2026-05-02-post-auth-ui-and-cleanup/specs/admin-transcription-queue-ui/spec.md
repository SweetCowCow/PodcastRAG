## MODIFIED Requirements

### Requirement: Admin page exposes a Transcription Queue tab

The admin page SHALL expose a "轉錄序列" (zh) / "Transcription Queue" (en) tab as the 6th admin tab, positioned after the Schedule tab and before the External API Status tab. The tab SHALL be reachable at route `admin-queue` (page state value). The tab SHALL display queue rows fetched from `GET /admin/queue` grouped into three sub-tabs by status:

| Sub-tab key | Label (zh) | Label (en) | Statuses included |
| ----------- | ---------- | ---------- | ----------------- |
| `active`    | 進行中     | Active     | pending, running  |
| `completed` | 已完成     | Completed  | completed         |
| `closed`    | 已結束     | Closed     | failed, cancelled |

Each sub-tab label SHALL include a count badge showing the total rows in that sub-tab (sum of constituent statuses). The active sub-tab indicator SHALL use `TOKEN.accent` for the underline/highlight; inactive sub-tabs SHALL use `TOKEN.textSecondary`.

Within the `active` sub-tab, all `running` rows SHALL appear above all `pending` rows (no section headers between them — visual ordering only). Within the `closed` sub-tab, rows SHALL still group by status into "失敗" / "Failed" and "已取消" / "Cancelled" sections. Within the `completed` sub-tab, rows SHALL render as a single flat list with no section header.

Within the `active` sub-tab, each `pending` row SHALL render a queue-position badge displaying its 1-based ordinal position within the pending segment (the topmost pending row shows `1`, the next shows `2`, and so on). The position numbering SHALL be derived purely from the rendered order of pending rows; it SHALL NOT be persisted in the API response. `running` rows SHALL NOT render a position badge — their status badge already conveys "executing".

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

#### Scenario: Active sub-tab shows running rows above pending rows with position numbers

- **GIVEN** the queue has 3 pending rows (P1, P2, P3) and 1 running row (R1), desktop viewport
- **WHEN** the user views the `active` sub-tab
- **THEN** the rendered order from top to bottom SHALL be R1, P1, P2, P3
- **AND** R1 SHALL NOT render a queue-position badge
- **AND** P1 SHALL render a queue-position badge showing `1`
- **AND** P2 SHALL render a queue-position badge showing `2`
- **AND** P3 SHALL render a queue-position badge showing `3`

##### Example: queue-position numbering after drag-to-reorder

- **GIVEN** active sub-tab displays R1, P1(pos=1), P2(pos=2), P3(pos=3)
- **WHEN** the user drags P3 above P1
- **THEN** the rendered order becomes R1, P3, P1, P2
- **AND** the position badges become P3=1, P1=2, P2=3

#### Scenario: Active sub-tab on mobile

- **GIVEN** the queue has 3 pending rows and 1 running row, mobile viewport
- **WHEN** the user views the `active` sub-tab
- **THEN** running rows SHALL still appear above pending rows (same ordering rule as desktop)
- **AND** each pending row SHALL render its queue-position badge
- **AND** each pending row SHALL render in a vertical stack with metadata stacked above wrapped action buttons
- **AND** no drag handle (⋮⋮) SHALL appear

#### Scenario: Closed sub-tab shows failed and cancelled with section headers

- **GIVEN** the queue has 2 failed rows and 1 cancelled row
- **WHEN** the user views the `closed` sub-tab
- **THEN** the sub-tab SHALL render two sections: "失敗" / "Failed" with 2 rows and "已取消" / "Cancelled" with 1 row
