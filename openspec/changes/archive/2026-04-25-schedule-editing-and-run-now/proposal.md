## Why

使用者在後台排程管理頁可以建立排程、toggle 啟用、刪除、同步集數、刪除節目，但是：

1. **無法編輯已建立的排程**——想把「每天轉」改成「每週轉」、換 whisper model、調整 max_episodes 全部做不到，只能刪掉重建（而重建會失去原本 enabled 狀態的時間戳）
2. **無法立即執行單一節目的轉錄**——目前只有「同步所有」按鈕，而且它現在是呼叫 `POST /shows/{id}/transcribe-all` 把節目的所有未轉錄集數全部 enqueue，沒辦法只轉最新幾集。大量集數節目（例如 200 集的 The Daily）會一次塞 200 個任務給 worker
3. **全量 transcribe-all 不符合排程設定**——即使 schedule 設 `max_episodes=5`，手動同步仍會 enqueue 全部。排程的意圖和手動觸發行為脫鉤

## What Changes

### 後端

- 新增 `POST /shows/{show_id}/transcribe-latest?max_episodes=N` 端點：
  - 先呼叫既有 `fetch_and_parse` + upsert 邏輯同步新集數（重用 `POST /shows/{id}/sync` 的邏輯，抽成 shared service function）
  - 按 `episodes.published_at` 由新到舊挑出 `transcript.status != completed`（含 pending、processing、failed、無 transcript）的前 N 集
  - 每一集建立或重設 transcript 為 pending，呼叫 `enqueue_transcription`
  - `max_episodes` 參數優先序：query param > `show_schedules.max_episodes`（若該節目有 schedule 且值 > 0）> 預設 5
  - 回 HTTP 202 + `{ queued: int, synced: { added: int, updated: int } }`

### 前端（`ScheduleTab`）

- 每張卡片加 **「編輯」** 按鈕，點擊打開 `FormModal`（新共用元件）
  - 表單欄位：frequency（select）、run_time（time input）、whisper_model（select）、max_episodes（number）
  - 提交時呼叫 `PUT /shows/{id}/schedule` 帶所有欄位；成功後 reload schedules 並關閉 modal
- 每張卡片加 **「立刻執行」** 按鈕，點擊直接呼叫 `POST /shows/{id}/transcribe-latest`
  - 不跳 modal（非破壞性操作）
  - 請求中按鈕 disabled + 顯示 loading
  - 成功後 alert「已排入 X 集轉錄（新增 Y 集／更新 Z 集）」
  - 失敗 alert 錯誤訊息
- 頂部「同步所有」按鈕改為對所有 `schedule.enabled === true` 的節目呼叫新的 `transcribe-latest`（取代目前 `transcribe-all`）
  - 完成後 alert「已對 N 個啟用中節目排入轉錄」

### 共用元件

- 在 Shared.jsx 新增 `FormModal` 元件：
  - Props：`{ open, title, children, confirmLabel, cancelLabel, onConfirm, onCancel, submitDisabled }`
  - 外觀類似既有 `ConfirmModal`（全屏 backdrop + 置中卡片），但內容區接受 children 放任意表單欄位
  - 主按鈕用 primary（非 danger）

## Non-Goals

- **不做 Celery 自動重試**（`autoretry_for` / `retry_backoff`）——留給 B2 `concurrency-control-and-retry`
- **不做同時轉錄節流**（Redis semaphore / per-show throttle）——留給 B2
- 不修改既有 `POST /shows/{id}/transcribe-all` 端點（保留 API 相容性，但前端不再使用）
- 不做 UI 刷新進度顯示（per-episode 狀態、錯誤訊息）——留給 Change C `transcription-progress-visibility`
- 不做排程真正的 cron 觸發（Celery Beat）——那屬於更大的 Scheduler 功能

## Capabilities

### New Capabilities

（無——本 change 的後端端點屬於既有 `transcription-pipeline`，UI 按鈕屬於既有 `admin-show-management-ui`）

### Modified Capabilities

- `transcription-pipeline`：新增 transcribe-latest 端點（sync 再挑最新未完成的前 N 集 enqueue）
- `admin-show-management-ui`：卡片新增編輯與立即執行兩個按鈕；SyncAll 行為從 transcribe-all 改為 transcribe-latest

## Impact

- Affected specs: transcription-pipeline, admin-show-management-ui
- Affected code:
  - New:
    - src/Shared.jsx（既有檔，僅新增 FormModal 元件並 export）
  - Modified:
    - backend/app/api/transcripts.py（新增 POST /shows/{id}/transcribe-latest route）
    - backend/app/schemas/sync.py（新增 TranscribeLatestResponse schema，或延用現有 + BatchTranscribeResponse 組合）
    - backend/app/api/shows.py（將 sync show 邏輯抽成可重用的 service function，供 transcripts.py 呼叫）
    - backend/app/services/rss_parser.py 或新增 backend/app/services/sync.py（shared sync function；擇一放）
    - src/AdminPage.jsx（ScheduleTab 加編輯、立即執行按鈕、FormModal 使用、SyncAll 行為變更）
    - src/Shared.jsx（FormModal）
  - Removed:（無）
