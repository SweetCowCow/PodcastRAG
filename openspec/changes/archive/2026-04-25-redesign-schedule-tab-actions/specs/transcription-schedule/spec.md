## MODIFIED Requirements

### Requirement: ScheduleTab frontend fetches real data

The frontend `ScheduleTab` component SHALL fetch `GET /admin/schedules` on mount and render the returned list. The loading state SHALL show a spinner while the request is in flight. On error, an error message SHALL be displayed. The legacy in-card enable/disable toggle SHALL NOT be rendered on cards. Editing a show's `enabled` field SHALL occur exclusively inside the "編輯排程" / "Edit Schedule" modal as a labelled "自動轉錄" / "Auto Transcribe" form field, and saving the modal SHALL call `PUT /shows/{show_id}/schedule` with all edited fields including `enabled`. The "Auto Transcribe" field SHALL display a helper text indicating that the setting will take effect once cron functionality is implemented (currently no runtime behaviour). The legacy "Sync All" page-level button SHALL NOT be rendered; batch operations SHALL instead be driven by the selection-based batch action bar (see admin-show-management-ui).

#### Scenario: Tab loads real schedule list on mount

- **WHEN** `ScheduleTab` mounts and `GET /admin/schedules` returns a list of shows
- **THEN** the tab SHALL render one card per show using API-returned fields; hardcoded mock data SHALL NOT be rendered

#### Scenario: Auto Transcribe field appears in Edit Schedule modal

- **WHEN** the user opens the "編輯排程" modal for a show
- **THEN** the modal SHALL render an "自動轉錄" form field bound to the schedule's `enabled` value
- **AND** the field SHALL display helper text noting the setting awaits the cron feature

#### Scenario: Saving the Edit Schedule modal persists enabled

- **WHEN** the user toggles the "自動轉錄" field in the modal and clicks the modal's confirm button
- **THEN** the frontend SHALL call `PUT /shows/{show_id}/schedule` with the updated `enabled` value
- **AND** on success the card SHALL be refreshed via `GET /admin/schedules`

#### Scenario: Legacy in-card toggle is removed

- **WHEN** any show card is rendered
- **THEN** the card SHALL NOT render the previous enable/disable toggle widget on the card body

#### Scenario: Legacy Sync All button is removed

- **WHEN** the `ScheduleTab` page header is rendered
- **THEN** the page SHALL NOT render the legacy "Sync All" / "同步所有" button
- **AND** batch operations SHALL be reachable only through the selection-based batch action bar

