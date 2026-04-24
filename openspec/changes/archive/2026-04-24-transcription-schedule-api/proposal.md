## Why

後台「轉錄排程管理」頁面目前使用硬寫的 mock 資料，所有操作（新增排程、切換啟用、同步）都只改本地 state，重新整理即消失。需要真實的後端 API 來持久化每個節目的排程設定，並讓前端反映真實狀態。

## What Changes

- 新增 `show_schedules` DB 資料表，儲存每個節目的排程設定（頻率、執行時間、Whisper 模型、最大集數、啟用狀態）
- 新增後端 API：`GET /shows/{show_id}/schedule`、`PUT /shows/{show_id}/schedule`、`DELETE /shows/{show_id}/schedule`
- 新增 `GET /admin/schedules` 端點，一次列出所有節目的排程設定與轉錄進度摘要（pending 集數、最後執行時間）
- 前端 `ScheduleTab` 改為掛載時 fetch 真實排程列表，取代硬寫的 mock shows
- 前端 RSS 預覽改呼叫既有的 `POST /shows`（建立節目）或直接呼叫 RSS parser API
- 前端「同步所有」按鈕改呼叫既有的 `POST /shows/{show_id}/transcribe-all`
- 前端新增排程表單送出後呼叫 `PUT /shows/{show_id}/schedule` 持久化設定

## Non-Goals

- 不實作 Celery Beat 或任何真正的 cron 排程執行（排程設定僅作為使用者偏好記錄，`nextRun` 為計算值；自動觸發屬未來功能）
- 不修改既有的 `POST /shows/{show_id}/transcribe-all` 邏輯
- 不實作排程執行歷史 log 資料表

## Capabilities

### New Capabilities

- `transcription-schedule`: 每個節目的轉錄排程設定 CRUD API，以及 admin 列表端點（含進度摘要）

### Modified Capabilities

- `rss-feed`: 新增 `GET /rss-preview?url=<rss_url>` 端點，回傳節目名稱、集數數量與最新發佈日期（供前端建立排程前預覽 RSS feed 使用）

## Impact

- 新增 DB migration：`show_schedules` 資料表
- 新增後端檔案：`backend/app/models/show_schedule.py`、`backend/app/schemas/schedule.py`、`backend/app/api/schedules.py`
- 修改後端：`backend/app/main.py`（掛載新 router）、`backend/app/api/shows.py`（新增 RSS preview endpoint）
- 修改前端：`src/AdminPage.jsx`（`ScheduleTab` 串接真實 API）
- 新增 Alembic migration 檔案
