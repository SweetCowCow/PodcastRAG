# admin-show-management-ui Specification

## Purpose

TBD - created by archiving change 'admin-show-crud-ui'. Update Purpose after archive.

## Requirements

### Requirement: Admin schedule card exposes show-level actions

The admin `ScheduleTab` SHALL render a `selection checkbox`, the show metadata, a primary "立刻執行轉錄" / "Run Transcribe Now" button, and a "⋯" overflow menu on each show card. The "立刻執行轉錄" button and the overflow menu's "編輯排程" / "Edit Schedule" and "移除排程" / "Remove Schedule" entries SHALL be shown only when the card's `schedule` field is not null. The "新增排程" / "Add Schedule" overflow entry SHALL be shown only when the card's `schedule` field is null. The selection checkbox, "更新節目集數" / "Refresh Episodes" overflow entry, and "刪除節目" / "Delete Show" overflow entry SHALL always be shown. The legacy in-card enable toggle, "Sync Episodes" button, "Edit Schedule" button, "Remove Schedule" button, and "Delete Show" button SHALL NOT be rendered as standalone card buttons.

#### Scenario: Card with schedule shows checkbox, primary button, and full overflow menu

- **WHEN** a show card is rendered and its `schedule` field is an object
- **THEN** the card SHALL display a selection checkbox, the show metadata, the "立刻執行轉錄" button, and a "⋯" overflow menu
- **AND** the overflow menu SHALL contain entries: "更新節目集數", "編輯排程", "移除排程", "刪除節目"
- **AND** the overflow menu SHALL NOT contain a "新增排程" entry

#### Scenario: Card without schedule hides schedule-only entries and exposes Add Schedule

- **WHEN** a show card is rendered and its `schedule` field is null
- **THEN** the card SHALL display the selection checkbox, the show metadata, and the "⋯" overflow menu
- **AND** the "立刻執行轉錄" button SHALL NOT be rendered
- **AND** the overflow menu SHALL contain entries in this order: "新增排程", "更新節目集數", "刪除節目"
- **AND** the menu SHALL NOT contain "編輯排程" or "移除排程"

#### Scenario: Legacy in-card toggle is removed

- **WHEN** any show card is rendered
- **THEN** the card SHALL NOT render the previous enable/disable toggle widget on the card body


<!-- @trace
source: redesign-schedule-tab-actions
updated: 2026-04-25
code:
  - index.html
  - src/Shared.jsx
  - src/AdminPage.jsx
  - docs/case-studies/sync-naming-redesign.md
-->

---
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
### Requirement: Remove Schedule deletes only the schedule row

The "Remove Schedule" action SHALL call `DELETE /shows/{show_id}/schedule` after confirmation. On success the show SHALL remain in the list, but its card SHALL re-render with `schedule: null` (showing the "未設定" badge and hiding the "Remove Schedule" button).

#### Scenario: Remove Schedule succeeds

- **WHEN** the user confirms "Remove Schedule" for a show with a schedule
- **THEN** the frontend SHALL call `DELETE /shows/{show_id}/schedule`
- **AND** on HTTP 204 response, the card SHALL re-render with the schedule removed and the show SHALL remain in the list


<!-- @trace
source: admin-show-crud-ui
updated: 2026-04-24
code:
  - CLAUDE.md
  - prod-select.png
-->

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


<!-- @trace
source: redesign-schedule-tab-actions
updated: 2026-04-25
code:
  - index.html
  - src/Shared.jsx
  - src/AdminPage.jsx
  - docs/case-studies/sync-naming-redesign.md
-->

---
### Requirement: PodcastSelect remains read-only

The public-facing `PodcastSelect` page SHALL NOT render any create, edit, or delete controls for shows. Management actions SHALL be accessible only via the admin area.

#### Scenario: PodcastSelect has no management buttons

- **WHEN** the `PodcastSelect` page is rendered for any user
- **THEN** the page SHALL NOT display any "Add Show", "Edit Show", "Delete Show", or equivalent buttons

<!-- @trace
source: admin-show-crud-ui
updated: 2026-04-24
code:
  - CLAUDE.md
  - prod-select.png
-->

---
### Requirement: Queue status endpoint reports live transcription throughput

The backend SHALL expose `GET /admin/queue-status` returning a JSON body with `active` (count of in-flight transcription tasks, read from Redis counter `transcribe:global:active_count`), `pending_in_queue` (count of tasks currently waiting in the Celery broker queue, read from `LLEN celery`), `pending_in_db` (count of `transcripts` rows with `status='pending'`), and `max_concurrent` (the configured `MAX_CONCURRENT_TRANSCRIPTIONS` value). The endpoint SHALL respond with HTTP 200.

#### Scenario: All counters reported

- **WHEN** a client calls `GET /admin/queue-status` with 1 task actively running, 2 tasks in the broker queue, 5 pending transcripts in DB, and `MAX_CONCURRENT_TRANSCRIPTIONS=1`
- **THEN** the response SHALL equal `{"active": 1, "pending_in_queue": 2, "pending_in_db": 5, "max_concurrent": 1}`

#### Scenario: Empty queue reports zeros

- **WHEN** a client calls `GET /admin/queue-status` with no active tasks and no pending transcripts
- **THEN** the response SHALL contain `active=0`, `pending_in_queue=0`, and `pending_in_db=0`


<!-- @trace
source: concurrency-control-and-retry
updated: 2026-04-25
code:
  - src/AdminPage.jsx
  - backend/app/api/admin.py
  - CLAUDE.md
  - backend/app/workers/tasks.py
  - backend/app/main.py
  - backend/requirements.txt
  - backend/app/workers/throttle.py
  - backend/app/schemas/admin.py
  - backend/app/services/transcription/openai_provider.py
  - backend/app/core/config.py
-->

---
### Requirement: ScheduleTab shows live queue status

The admin `ScheduleTab` SHALL render a queue status indicator near the page header containing the current `active` / `max_concurrent` ratio and the `pending_in_queue` count. Data SHALL be fetched from `GET /admin/queue-status` on tab mount and SHALL refresh every 30 seconds while the tab is mounted. When the user navigates away from the tab, the polling interval SHALL be cleared.

#### Scenario: Indicator visible on mount

- **WHEN** the user opens the 轉錄排程 tab and the queue-status endpoint returns `{active: 0, max_concurrent: 1, pending_in_queue: 0}`
- **THEN** the indicator SHALL display "執行中 0/1" and "佇列中 0" (or the English equivalent)

#### Scenario: Indicator updates via polling

- **WHEN** the tab has been mounted for 30 seconds and the server state has changed so that the endpoint now returns `{active: 1, pending_in_queue: 3}`
- **THEN** the indicator SHALL re-render with the new values without manual reload

#### Scenario: Polling stops on unmount

- **WHEN** the user navigates from the 轉錄排程 tab to another admin tab
- **THEN** the polling interval SHALL be cleared and no further `GET /admin/queue-status` requests SHALL be sent

<!-- @trace
source: concurrency-control-and-retry
updated: 2026-04-25
code:
  - src/AdminPage.jsx
  - backend/app/api/admin.py
  - CLAUDE.md
  - backend/app/workers/tasks.py
  - backend/app/main.py
  - backend/requirements.txt
  - backend/app/workers/throttle.py
  - backend/app/schemas/admin.py
  - backend/app/services/transcription/openai_provider.py
  - backend/app/core/config.py
-->

---
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

<!-- @trace
source: schedule-editing-and-run-now
updated: 2026-04-25
code:
  - CLAUDE.md
  - backend/app/core/config.py
  - backend/app/services/transcription/openai_provider.py
  - src/AdminPage.jsx
  - backend/app/workers/throttle.py
  - backend/requirements.txt
  - backend/app/api/transcripts.py
  - backend/app/api/shows.py
  - backend/app/workers/tasks.py
  - backend/app/schemas/sync.py
  - backend/app/api/admin.py
  - backend/app/services/sync.py
  - backend/app/main.py
  - src/Shared.jsx
  - backend/app/schemas/admin.py
-->

---
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


<!-- @trace
source: redesign-schedule-tab-actions
updated: 2026-04-25
code:
  - index.html
  - src/Shared.jsx
  - src/AdminPage.jsx
  - docs/case-studies/sync-naming-redesign.md
-->

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


<!-- @trace
source: redesign-schedule-tab-actions
updated: 2026-04-25
code:
  - index.html
  - src/Shared.jsx
  - src/AdminPage.jsx
  - docs/case-studies/sync-naming-redesign.md
-->

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

#### Scenario: Single-show "立刻執行轉錄" still skips the confirm modal

- **WHEN** the user clicks the per-card "立刻執行轉錄" button on a single card
- **THEN** the frontend SHALL call `POST /shows/{show_id}/transcribe-latest` directly without opening the batch confirmation modal


<!-- @trace
source: redesign-schedule-tab-actions
updated: 2026-04-25
code:
  - index.html
  - src/Shared.jsx
  - src/AdminPage.jsx
  - docs/case-studies/sync-naming-redesign.md
-->

---
### Requirement: Add Schedule from card without schedule

When a show card has `schedule == null`, the "新增排程" / "Add Schedule" entry in the card's "⋯" overflow menu SHALL open the same modal used by "編輯排程" / "Edit Schedule", pre-filled with default values: `enabled=false`, `frequency="manual"`, `run_time="06:00"`, `whisper_model="large-v3"`, `max_episodes=0`. On confirm, the frontend SHALL call `PUT /shows/{show_id}/schedule` with the form values; on success the frontend SHALL re-fetch `GET /admin/schedules` so the card re-renders with the new schedule. On cancel or backdrop click, no network request SHALL be sent.

#### Scenario: Add Schedule opens modal with defaults

- **WHEN** the user opens the "⋯" menu on a card whose `schedule` is null and clicks "新增排程"
- **THEN** a modal SHALL appear titled "編輯排程" / "Edit Schedule"
- **AND** the form fields SHALL be pre-populated with `enabled=false`, `frequency="manual"`, `run_time="06:00"`, `whisper_model="large-v3"`, `max_episodes=0`
- **AND** no network request SHALL be sent until the user clicks the modal's confirm button

#### Scenario: Saving Add Schedule modal creates schedule via PUT

- **WHEN** the user fills out the Add Schedule modal and clicks the confirm button
- **THEN** the frontend SHALL call `PUT /shows/{show_id}/schedule` with `{enabled, frequency, run_time, whisper_model, max_episodes}`
- **AND** on HTTP 200 response, the frontend SHALL re-fetch `GET /admin/schedules` and the card SHALL re-render with the new `schedule` object

#### Scenario: Cancelling Add Schedule modal sends no request

- **WHEN** the Add Schedule modal is open and the user clicks "取消" or the backdrop
- **THEN** the modal SHALL close and no `PUT /shows/{show_id}/schedule` request SHALL be sent


<!-- @trace
source: redesign-schedule-tab-actions
updated: 2026-04-25
code:
  - index.html
  - src/Shared.jsx
  - src/AdminPage.jsx
  - docs/case-studies/sync-naming-redesign.md
-->

---
### Requirement: ScheduleTab page header uses Add Show language

The `ScheduleTab` page header button that opens the create-show form SHALL be labelled "新增節目" / "Add Show" (NOT "新增排程" / "Add Schedule"). The form panel that opens SHALL be titled "新增節目轉錄排程" / "New Show with Transcription Schedule". This wording disambiguates the page-header action (which creates BOTH a `Show` row and a `Schedule` row in one flow) from the per-card "新增排程" / "Add Schedule" overflow action (which creates a Schedule for an existing Show).

#### Scenario: Page header button label

- **WHEN** the `ScheduleTab` page header is rendered
- **THEN** the right-side action button SHALL display the label "新增節目" / "Add Show"
- **AND** the legacy label "新增排程" / "Add Schedule" SHALL NOT appear in the page header

#### Scenario: Create-show panel title

- **WHEN** the user clicks "新增節目" and the create form panel expands
- **THEN** the panel SHALL show the heading "新增節目轉錄排程" / "New Show with Transcription Schedule"

<!-- @trace
source: redesign-schedule-tab-actions
updated: 2026-04-25
code:
  - index.html
  - src/Shared.jsx
  - src/AdminPage.jsx
  - docs/case-studies/sync-naming-redesign.md
-->
---
### Requirement: Schedule card exposes expandable transcription progress panel

Each show card in the admin `ScheduleTab` SHALL provide an expand/collapse control that toggles a progress panel sourced from `GET /shows/{show_id}/transcription-status`, so that administrators can see real-time aggregated transcription state for that show without visiting individual episodes.

The expand control SHALL default to collapsed on initial render. While expanded, the panel SHALL poll the `transcription-status` endpoint every 5 seconds and re-render on each response. While collapsed the panel SHALL NOT issue any requests. The polling SHALL stop and the interval SHALL be cleared when: the panel is collapsed, the card is removed from the DOM, or the user navigates away from the ScheduleTab.

The expanded panel SHALL contain three regions rendered top-to-bottom:

1. A counts row showing `pending` / `processing` / `completed` / `failed` labelled counts (Chinese: "待處理 / 處理中 / 完成 / 失敗")
2. A "currently processing" list rendering each entry in `currently_processing` as `<episode_title>`; when the list is empty the region SHALL display a muted placeholder ("目前沒有轉錄中" / "None currently processing") and SHALL NOT be hidden entirely
3. A "recent failures" list rendering each entry in `recent_failures` as `<episode_title>` with a badge for `error_category` and the `error_message` (up to 200 characters); when the list is empty the region SHALL display a muted placeholder ("近期沒有失敗" / "No recent failures") and SHALL NOT be hidden entirely

The `error_category` badge SHALL use the same variant mapping defined in the `admin-external-api-status-ui` capability so that one category yields a single consistent colour across the admin UI.

#### Scenario: Collapsed card makes no requests

- **WHEN** the card is rendered and the user has not clicked the expand control
- **THEN** no `GET /shows/{id}/transcription-status` request SHALL be issued for that card

#### Scenario: Expanding triggers first fetch and polling

- **WHEN** the user clicks the expand control on a card
- **THEN** one immediate `GET /shows/{id}/transcription-status` request SHALL be issued for that show's id
- **AND** a 5-second polling interval SHALL begin making subsequent requests
- **AND** the panel SHALL render the response's three regions according to the rules above

#### Scenario: Collapsing stops polling

- **WHEN** the user clicks the expand control on an already-expanded card
- **THEN** the panel SHALL unmount (or hide) its regions
- **AND** the 5-second polling interval SHALL be cleared within the same event loop turn as the collapse

#### Scenario: Empty sections rendered explicitly

- **WHEN** the response has `currently_processing = []` and `recent_failures = []`
- **THEN** both regions SHALL still render with their muted-placeholder text and SHALL NOT be hidden or removed from the DOM

#### Scenario: Failure category drives badge variant

- **WHEN** a `recent_failures` entry has `error_category = "quota_exceeded"`
- **THEN** that failure SHALL render with the `danger` badge variant labelled "額度不足" (zh) / "Quota Exceeded" (en)

<!-- @trace
source: transcription-progress-visibility
updated: 2026-04-27
code:
  - backend/app/api/admin.py
  - src/Shared.jsx
  - backend/alembic/versions/e3f4a5b6c7d8_add_transcripts_updated_at.py
  - backend/pytest.ini
  - backend/app/schemas/transcription_status.py
  - backend/app/api/shows.py
  - backend/app/services/transcription/openai_provider.py
  - src/AdminPage.jsx
  - src/ExternalApiStatusTab.jsx
  - backend/app/services/api_health.py
  - index.html
  - backend/app/services/rag.py
  - backend/app/schemas/api_health.py
  - backend/app/services/embedding.py
  - backend/app/models/transcript.py
tests:
  - backend/tests/__init__.py
  - backend/tests/test_api_health.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
-->

---
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
### Requirement: Schedule modal frequency selector excludes hourly and falls back gracefully

The schedule edit/create modal frequency selector SHALL offer exactly three options labelled "每天" / "Daily" (`daily`), "每週" / "Weekly" (`weekly`), and "手動" / "Manual" (`manual`). The legacy `hourly` option SHALL NOT appear in the dropdown.

When opening the modal for an existing schedule whose persisted `frequency` value is not in `{daily, weekly, manual}` (notably the legacy `hourly`), the form SHALL initialize the frequency field to `daily` (fallback), SHALL display a warning helper text below the frequency selector reading "原設定『每小時』已停用，已改為每天，請確認後儲存。" / "The previous 'hourly' setting is no longer supported; switched to daily. Please confirm and save." in `TOKEN.warning` color, and SHALL NOT issue any `PUT /shows/{show_id}/schedule` request automatically. The persisted DB value SHALL remain unchanged until the user clicks Save.

#### Scenario: Frequency dropdown shows three options

- **WHEN** the user opens the schedule edit/create modal
- **THEN** the frequency `<select>` SHALL contain exactly three `<option>` elements with values `daily`, `weekly`, `manual`
- **AND** no option SHALL have value `hourly`

#### Scenario: Existing hourly schedule falls back to daily on display

- **GIVEN** a show with persisted `frequency=hourly` in the database
- **WHEN** the user opens its schedule edit modal
- **THEN** the frequency selector SHALL display `每天` / `Daily` (value `daily`)
- **AND** a warning helper text SHALL appear below the selector
- **AND** no network request SHALL be sent until the user clicks Save

#### Scenario: User saves the fallback to persist daily

- **GIVEN** the modal is open with frequency falling back from `hourly` to `daily`
- **WHEN** the user clicks Save without changing the frequency
- **THEN** the frontend SHALL call `PUT /shows/{show_id}/schedule` with `frequency=daily`
- **AND** on HTTP 200 the persisted value SHALL be `daily`

<!-- @trace
source: queue-tabs-and-schedule-cleanup
updated: 2026-04-30
-->


<!-- @trace
source: queue-tabs-and-schedule-cleanup
updated: 2026-04-30
code:
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/models/show_schedule.py
  - backend/app/schemas/schedule.py
  - src/AdminPage.jsx
  - backend/app/workers/cron_tick.py
  - src/QueueTab.jsx
  - backend/app/api/schedules.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/alembic/versions/j8e9f0a1b2c3_add_day_of_week_to_show_schedules.py
tests:
  - backend/tests/test_cron_tick_is_due.py
-->

---
### Requirement: Schedule modal renders day_of_week selector for weekly frequency

The schedule edit/create modal SHALL render a "星期幾" / "Day of Week" segmented button group bound to the schedule's `day_of_week` field whenever (and only when) the frequency selector value is `weekly`. The segmented group SHALL contain exactly seven buttons in order representing Monday through Sunday with labels:

| `day_of_week` value | Label (zh) | Label (en) |
| ------------------- | ---------- | ---------- |
| 0                   | 一         | Mon        |
| 1                   | 二         | Tue        |
| 2                   | 三         | Wed        |
| 3                   | 四         | Thu        |
| 4                   | 五         | Fri        |
| 5                   | 六         | Sat        |
| 6                   | 日         | Sun        |

The selected button SHALL use `TOKEN.accent` background with white text; unselected buttons SHALL use `TOKEN.surfaceRaised` background with `TOKEN.textSecondary` text. Exactly one button SHALL be selected at all times. Switching the frequency away from `weekly` SHALL hide the segmented group; switching back to `weekly` SHALL re-render it with the form's current `day_of_week` value preserved.

When opening the modal for an existing schedule, the segmented group SHALL be initialized to the schedule's persisted `day_of_week` value. When opening "Add Schedule" (no existing schedule), the segmented group SHALL default to `day_of_week=0` (Monday). The form SHALL submit `day_of_week` along with other fields when the user clicks Save.

#### Scenario: Day picker visible only when frequency is weekly

- **GIVEN** the schedule edit modal is open with `frequency=daily`
- **WHEN** the user changes the frequency selector to `weekly`
- **THEN** the day_of_week segmented group SHALL appear with seven buttons
- **AND** when the user changes the frequency back to `daily` or to `manual`, the segmented group SHALL be hidden

#### Scenario: Existing weekly schedule pre-selects persisted day

- **GIVEN** a schedule with `frequency=weekly, day_of_week=2`
- **WHEN** the user opens the edit modal
- **THEN** the segmented group SHALL render with the third button ("三" / "Wed") selected

#### Scenario: User changes day and saves

- **GIVEN** the modal is open with `frequency=weekly, day_of_week=2`
- **WHEN** the user clicks the "五" / "Fri" button and clicks Save
- **THEN** the frontend SHALL call `PUT /shows/{show_id}/schedule` with `day_of_week=4`

<!-- @trace
source: queue-tabs-and-schedule-cleanup
updated: 2026-04-30
-->


<!-- @trace
source: queue-tabs-and-schedule-cleanup
updated: 2026-04-30
code:
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/models/show_schedule.py
  - backend/app/schemas/schedule.py
  - src/AdminPage.jsx
  - backend/app/workers/cron_tick.py
  - src/QueueTab.jsx
  - backend/app/api/schedules.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/alembic/versions/j8e9f0a1b2c3_add_day_of_week_to_show_schedules.py
tests:
  - backend/tests/test_cron_tick_is_due.py
-->

---
### Requirement: Schedule modal hides run_time and day_of_week for manual frequency

When the schedule edit/create modal frequency selector value is `manual`, the modal SHALL hide both the "執行時間" / "Run Time" input and the "星期幾" / "Day of Week" segmented group. The Whisper model selector and the "每次最多轉錄集數" / "Max Episodes Per Run" input SHALL remain visible regardless of frequency. A helper text "不會自動執行，需從清單點『立即執行』" / "Will not run automatically. Trigger manually from the list." SHALL appear below the frequency selector when frequency is `manual`.

The form SHALL still submit `run_time` and `day_of_week` to the backend when frequency is `manual` (using the values currently held in form state; defaults `run_time=06:00`, `day_of_week=0` apply when the user has not modified them) so the backend row stays well-formed.

#### Scenario: Manual frequency hides time and day inputs

- **GIVEN** the modal is open
- **WHEN** the user changes the frequency to `manual`
- **THEN** the "執行時間" input and the "星期幾" segmented group SHALL be hidden
- **AND** the Whisper model selector and "每次最多轉錄集數" input SHALL remain visible
- **AND** a "不會自動執行" helper text SHALL appear below the frequency selector

#### Scenario: Manual frequency saves run_time placeholder

- **GIVEN** the modal is open with frequency switched to `manual` and run_time still at its prior value `06:00`
- **WHEN** the user clicks Save
- **THEN** the request body SHALL include `frequency=manual`, `run_time=06:00`, `day_of_week=0` (or whichever value is currently in form state)

<!-- @trace
source: queue-tabs-and-schedule-cleanup
updated: 2026-04-30
-->


<!-- @trace
source: queue-tabs-and-schedule-cleanup
updated: 2026-04-30
code:
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/models/show_schedule.py
  - backend/app/schemas/schedule.py
  - src/AdminPage.jsx
  - backend/app/workers/cron_tick.py
  - src/QueueTab.jsx
  - backend/app/api/schedules.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/alembic/versions/j8e9f0a1b2c3_add_day_of_week_to_show_schedules.py
tests:
  - backend/tests/test_cron_tick_is_due.py
-->

---
### Requirement: Schedule modal shows dynamic next-run hint

The schedule edit/create modal SHALL display a single-line dynamic hint in `TOKEN.textMuted` 12px below the "執行時間" input (or below the frequency selector when frequency is `manual` and the run_time input is hidden). The hint text SHALL be derived from the current form state per the table below:

| frequency | Hint text (zh)                                  | Hint text (en)                                |
| --------- | ----------------------------------------------- | --------------------------------------------- |
| `daily`   | 每日 `{run_time}` (UTC) 觸發                    | Runs daily at `{run_time}` (UTC)              |
| `weekly`  | 每週`{day_zh}` `{run_time}` (UTC) 觸發          | Runs every `{day_en}` at `{run_time}` (UTC)   |
| `manual`  | 不會自動執行                                    | Will not run automatically                    |

`{day_zh}` and `{day_en}` SHALL match the day labels defined in the day_of_week selector requirement (e.g., `day_of_week=2` → `三` / `Wed`).

The hint SHALL update synchronously whenever the user changes any of `frequency`, `run_time`, or `day_of_week` in the form.

#### Scenario: Daily hint reflects run_time

- **GIVEN** the modal is open with `frequency=daily, run_time=06:00`
- **THEN** the hint SHALL read "每日 06:00 (UTC) 觸發" (zh) or "Runs daily at 06:00 (UTC)" (en)

#### Scenario: Weekly hint reflects day and time

- **GIVEN** the modal is open with `frequency=weekly, day_of_week=2, run_time=09:30`
- **THEN** the hint SHALL read "每週三 09:30 (UTC) 觸發" (zh) or "Runs every Wed at 09:30 (UTC)" (en)

#### Scenario: Manual hint says no auto-run

- **GIVEN** the modal is open with `frequency=manual`
- **THEN** the hint SHALL read "不會自動執行" (zh) or "Will not run automatically" (en)

#### Scenario: Hint updates synchronously when frequency changes

- **GIVEN** the modal is open with `frequency=daily, run_time=06:00`
- **WHEN** the user changes the frequency to `weekly`
- **THEN** the hint SHALL immediately re-render to "每週一 06:00 (UTC) 觸發" (zh) using the form's current `day_of_week` (default 0 = Monday)

---
### Requirement: Schedule modal renders mobile-friendly layout

When `isMobile` is `true`, the schedule edit/create modal in `src/AdminPage.jsx` SHALL render its inner box with `width: min(95vw, 480)` (inheriting the shared `FormModal` mobile width). Internal field rows that use `gridTemplateColumns: '1fr 1fr 1fr'` on desktop SHALL collapse to `gridTemplateColumns: '1fr'` on mobile. The day_of_week segmented button group SHALL retain `flexWrap: 'wrap'` (already present); each day button SHALL have minimum touch target of 44 × 44 px. The Whisper model selector buttons SHALL retain `flexWrap: 'wrap'`.

When `isMobile` is `false`, the schedule modal SHALL render exactly as today (desktop layout, fixed grid columns, current button sizes).

#### Scenario: Modal fits 360 px viewport

- **GIVEN** mobile viewport at 360 px, schedule edit modal is opened
- **WHEN** the modal renders
- **THEN** the inner box width SHALL be at most 342 px (95% of 360)
- **AND** no field SHALL cause horizontal scroll within the modal

#### Scenario: Three-column row stacks on mobile

- **GIVEN** mobile viewport, schedule edit modal is opened
- **WHEN** the user views internal field rows that span three columns on desktop
- **THEN** the fields SHALL render stacked vertically (one per row)

#### Scenario: Day picker buttons meet touch target

- **GIVEN** mobile viewport, schedule edit modal with frequency=weekly
- **WHEN** the day_of_week segmented buttons render
- **THEN** each button SHALL have a hit area of at least 44 × 44 px

#### Scenario: Desktop modal unchanged

- **GIVEN** desktop viewport, schedule edit modal is opened
- **WHEN** the modal renders
- **THEN** the inner box SHALL render at 480 px wide
- **AND** three-column rows SHALL render side-by-side as today


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
### Requirement: Schedule cards stack vertically on mobile

When `isMobile` is `true`, each schedule card in the admin schedule list (`src/AdminPage.jsx`) SHALL render its content in a vertical stack: header (checkbox + title + badges) on top, metadata row (RSS URL / frequency / last refresh / whisper model) directly below, and action buttons (查看進度 / 立刻執行轉錄 / 更多操作) on a wrapped row at the bottom. The metadata row SHALL retain `flexWrap: 'wrap'` so individual metadata items wrap as needed. The action button area SHALL change from `flexShrink: 0` (desktop, never shrinks) to `flexWrap: 'wrap'` allowing buttons to wrap onto multiple lines.

The card outer container border, background, and `padding: '18px 22px'` SHALL be reduced on mobile to `padding: '14px 16px'` to give content more room.

When `isMobile` is `false`, schedule cards SHALL render exactly as today (single horizontal flex row with fixed action area on the right).

#### Scenario: Card stacks on mobile

- **GIVEN** mobile viewport, admin schedule list renders 3 shows
- **WHEN** the user views one card
- **THEN** the title row, metadata row, and action button row SHALL render stacked vertically (one above the other)

#### Scenario: Action buttons wrap on mobile

- **GIVEN** mobile viewport, a schedule card has 3 action buttons
- **WHEN** the buttons would not fit on a single row
- **THEN** they SHALL wrap onto multiple rows (no horizontal overflow)

#### Scenario: Desktop card unchanged

- **GIVEN** desktop viewport
- **WHEN** the schedule list renders
- **THEN** each card SHALL render as a single horizontal flex row with the action button area fixed on the right (no shrink)

<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
-->

<!-- @trace
source: queue-tabs-and-schedule-cleanup
updated: 2026-04-30
-->

<!-- @trace
source: queue-tabs-and-schedule-cleanup
updated: 2026-04-30
code:
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/models/show_schedule.py
  - backend/app/schemas/schedule.py
  - src/AdminPage.jsx
  - backend/app/workers/cron_tick.py
  - src/QueueTab.jsx
  - backend/app/api/schedules.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/alembic/versions/j8e9f0a1b2c3_add_day_of_week_to_show_schedules.py
tests:
  - backend/tests/test_cron_tick_is_due.py
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