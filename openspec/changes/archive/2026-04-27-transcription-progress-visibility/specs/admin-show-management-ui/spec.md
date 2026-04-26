## ADDED Requirements

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
