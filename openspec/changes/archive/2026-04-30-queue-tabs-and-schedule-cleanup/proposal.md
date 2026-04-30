## Why

轉錄佇列分頁目前一次平鋪五個 status section（pending / running / completed / failed / cancelled），列數一多就要持續捲動，且使用者很少同時關心五種狀態 — 多半只想看「正在進行的」「失敗待處理的」或「歷史完成的」。同時排程編輯介面殘留已不被 cron 支援的 `hourly` 選項，且 weekly 寫死在週一（`backend/app/workers/cron_tick.py:213` 的 `weekday == 0`），使用者無法選星期，造成設定與實際行為脫節。

## What Changes

- 轉錄佇列分頁內部切成三個子分頁：`排隊中＋執行中` / `完成` / `失敗＋已取消`。三個子分頁仍隸屬於後台「轉錄序列」單一 admin tab，後端 API 不變。
- 排程頻率下拉選單砍掉 `hourly` 選項，改為 `每天 / 每週 / 手動` 三選；DB 中既有 `frequency='hourly'` 的 row 在前端讀取時 fallback 顯示為 `每天`（不自動寫回 DB，使用者下次編輯儲存時才更新）。
- 排程編輯 modal 改為條件式渲染：
  - `daily`：顯示「執行時間」
  - `weekly`：顯示「星期幾」（segmented button：一/二/三/四/五/六/日）+「執行時間」
  - `manual`：隱藏「執行時間」與「星期幾」，補一行「不會自動執行」說明
  - 三種模式皆顯示「Whisper 模型」與「每次最多轉錄集數」
- `show_schedules` 表新增 `day_of_week` 欄位（`INTEGER NOT NULL DEFAULT 0`，0=週一 ⋯ 6=週日，沿用 Python `datetime.weekday()` 慣例）。
- `cron_tick._is_due` 的 weekly 分支改讀 `schedule.day_of_week` 取代寫死的 `weekday == 0`。
- 排程編輯 modal 在「執行時間」下方新增動態提示文案（例：`每週一 09:30 (UTC) 觸發` / `每日 06:00 (UTC) 觸發` / `不會自動執行`）。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `admin-transcription-queue-ui`：佇列分頁渲染從 5 個平鋪 section 改為 3 個子分頁包裹原有 status 列；所有列內動作（拖曳、重試、忽略、強制取消）保持不變。
- `transcription-schedule`：`show_schedules` 新增 `day_of_week` 欄位；weekly 觸發條件從寫死週一改為比對 `day_of_week`。
- `admin-show-management-ui`：排程編輯 modal 移除 hourly 選項、新增 day_of_week segmented 選擇器、條件式渲染欄位、新增 fallback 邏輯與動態提示文案。

## Impact

- Affected specs: `admin-transcription-queue-ui`, `transcription-schedule`, `admin-show-management-ui`
- Affected code:
  - Modified:
    - src/QueueTab.jsx
    - src/AdminPage.jsx
    - backend/app/models/show_schedule.py
    - backend/app/workers/cron_tick.py
    - backend/app/schemas/schedule.py
    - backend/app/api/schedules.py
  - New:
    - backend/alembic/versions/<timestamp>_add_day_of_week_to_show_schedules.py
  - Removed: (none)
- 既有 `frequency='hourly'` row：cron 已不會觸發（`_is_due` 不認 hourly），故行為不變；UI 顯示 fallback 至 daily，使用者重新儲存後寫回 daily。
- DB migration 對既有列 backfill `day_of_week=0`（等同沿用原本寫死的「週一」行為），無破壞性。
