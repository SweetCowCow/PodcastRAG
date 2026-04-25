## ADDED Requirements

### Requirement: Queue status endpoint reports live transcription throughput

The backend SHALL expose `GET /admin/queue-status` returning a JSON body with `active` (count of in-flight transcription tasks, read from Redis counter `transcribe:global:active_count`), `pending_in_queue` (count of tasks currently waiting in the Celery broker queue, read from `LLEN celery`), `pending_in_db` (count of `transcripts` rows with `status='pending'`), and `max_concurrent` (the configured `MAX_CONCURRENT_TRANSCRIPTIONS` value). The endpoint SHALL respond with HTTP 200.

#### Scenario: All counters reported

- **WHEN** a client calls `GET /admin/queue-status` with 1 task actively running, 2 tasks in the broker queue, 5 pending transcripts in DB, and `MAX_CONCURRENT_TRANSCRIPTIONS=1`
- **THEN** the response SHALL equal `{"active": 1, "pending_in_queue": 2, "pending_in_db": 5, "max_concurrent": 1}`

#### Scenario: Empty queue reports zeros

- **WHEN** a client calls `GET /admin/queue-status` with no active tasks and no pending transcripts
- **THEN** the response SHALL contain `active=0`, `pending_in_queue=0`, and `pending_in_db=0`

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
