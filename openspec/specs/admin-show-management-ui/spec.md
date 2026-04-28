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