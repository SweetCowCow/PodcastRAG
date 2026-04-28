## Why

兩個後端 change（`db-driven-queue-and-real-cron`、`parallel-transcription-and-force-cancel`）archive 後留下一批前端工作未做：admin 沒有「轉錄序列」rows 列表、沒有 force-cancel 按鈕、沒有 max_concurrent input、排程 modal 缺欄位、刪 show 沒 confirm。後端 API 都已就緒，純前端工作。

## What Changes

- **新增「轉錄序列」admin tab**（第 6 個 tab，nav 位置在 Schedule 後面）：5 status 分組（pending / running / completed / failed / cancelled）、每 row 顯示 episode + show + status badge + 時間戳 + error_message + celery_task_id（折疊）
- **取消按鈕**：pending row 顯示普通「取消」呼叫 `POST /admin/queue/{id}/cancel`；running row 顯示紅色「強制取消」+ confirm dialog 呼叫 `POST /admin/queue/{id}/cancel?force=true`
- **重試 / 忽略**：failed row 顯示「重試」（重 enqueue 走 `POST /episodes/{id}/transcribe`）+「忽略」（`POST /admin/queue/{id}/ignore`）；ignored row 顯示灰底 + 「取消忽略」（`POST /admin/queue/{id}/unignore`）
- **並行上限調整**：tab 頂部加 `max_concurrent_transcriptions` 數字輸入框（max=3，超過顯 helper text「上限 3，受 worker concurrency 限制」/「Max 3, limited by worker concurrency」），onChange debounce 500ms 後呼叫 `PUT /admin/settings`
- **Drag reorder pending rows**：用手刻 mouseEvent（避免引入 dnd-kit；React via Babel CDN 環境用 ESM module 不便）讓 pending 區塊可拖；drop 後呼叫新後端 endpoint `PATCH /admin/queue/{id}/position` body `{"position": int}`，失敗 revert
- **後端：新 PATCH position endpoint**：在 transaction 內 recompute 受影響的其他 pending rows position（簡化：先把目標 row position 改成新值，再把區間內其他 rows 平移）
- **5s polling**：仿 ScheduleTab，hook 內 setInterval 5000ms 重抓 `GET /admin/queue` + `GET /admin/settings`
- **排程 modal 增補**（修改現有 ScheduleTab）：modal 加 `max_episodes_per_run` 數字輸入框（已是 r/w 必填）；卡片底 + modal 顯示 `last_refresh_at` + `last_refresh_status` + `last_refresh_message`（唯讀，依 status 上不同色）
- **刪 show confirm dialog**（修改現有 ScheduleTab）：點刪除前先呼叫 `GET /admin/queue` 過濾該 show_id 算 pending/running 數，dialog 顯示「將同時取消 N 筆 pending + M 筆 running queue rows」，confirm 後才呼叫 `DELETE /shows/{id}`

## Non-Goals

- 不改 queue 後端核心邏輯（除新 PATCH position endpoint）
- 不做拖動跨 status 區（只能在 pending 內拖）
- 不做 bulk 操作（多選 + 一次取消 / 一次重試）
- 不做轉錄序列頁的搜尋 / show filter
- 不引入 dnd-kit 等第三方套件（保持 CDN-only React + Babel 部署）
- 不改 polling 機制為 WebSocket / SSE
- 不重設計排程的「下次執行時間」「執行歷史」UI（屬未來 change）

## Capabilities

### New Capabilities

- `admin-transcription-queue-ui`: admin 後台的「轉錄序列」tab，含 rows 列表、cancel / force-cancel / retry / ignore / unignore 按鈕、max_concurrent input、pending drag reorder

### Modified Capabilities

- `transcription-queue`: 新增 `PATCH /admin/queue/{id}/position` endpoint 用於拖動排序
- `admin-show-management-ui`: 排程 modal 加 `max_episodes_per_run` 輸入；卡片 / modal 顯示 `last_refresh_*` 三欄；刪 show 加 cascade-aware confirm dialog

## Impact

- Affected specs: `admin-transcription-queue-ui` (new), `transcription-queue` (modified), `admin-show-management-ui` (modified)
- Affected code:
  - New:
    - src/QueueTab.jsx
  - Modified:
    - src/AdminPage.jsx
    - src/Shared.jsx
    - src/App.jsx
    - backend/app/api/queue.py
    - backend/app/schemas/queue.py
