## ADDED Requirements

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
