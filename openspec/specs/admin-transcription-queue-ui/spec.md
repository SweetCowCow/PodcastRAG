# admin-transcription-queue-ui Specification

## Purpose

TBD - created by archiving change 'transcription-queue-and-schedule-ui'. Update Purpose after archive.

## Requirements

### Requirement: Admin page exposes a Transcription Queue tab

The admin page SHALL expose a "轉錄序列" (zh) / "Transcription Queue" (en) tab as the 6th admin tab, positioned after the Schedule tab and before the External API Status tab. The tab SHALL be reachable at route `admin-queue` (page state value). The tab SHALL display queue rows fetched from `GET /admin/queue` grouped by status into 5 sections: pending, running, completed, failed, cancelled. Each row SHALL display the episode title, the show name, a status badge, the relevant timestamps (`enqueued_at`, `started_at`, `finished_at` when present), the `error_message` for failed/cancelled rows, and the `celery_task_id` (collapsible/folded by default for debug).

The tab SHALL poll `GET /admin/queue` and `GET /admin/settings` every 5 seconds while mounted; the polling SHALL stop when the tab unmounts or the user navigates away.

#### Scenario: Tab renders all five status sections

- **GIVEN** the queue contains rows with statuses pending, running, completed, failed, cancelled
- **WHEN** the user navigates to the Transcription Queue tab
- **THEN** the tab SHALL render 5 sections with section headers naming the status (or "空" / "Empty" if a section has no rows)
- **AND** each row SHALL show episode title, show name, status badge, and relevant timestamps

#### Scenario: Polling refreshes data every 5 seconds

- **GIVEN** the Transcription Queue tab is mounted
- **WHEN** 5 seconds elapse
- **THEN** the frontend SHALL re-call `GET /admin/queue` and `GET /admin/settings`
- **AND** when the tab unmounts, the polling interval SHALL be cleared


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