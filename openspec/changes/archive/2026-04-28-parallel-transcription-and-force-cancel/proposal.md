## Why

上一個 change `db-driven-queue-and-real-cron` 完成 DB-backed queue + dispatcher + cron tick，但 worker 仍是單 replica `--concurrency=1`，所以 `max_concurrent_transcriptions` setting 即使設 3，真實執行仍是序列。本 change 把 worker 升為固定 3 replica 達成真平行，並補上 stuck running row 的「強制取消」能力（順手清掉 2026-04-28 archive 後遺留的 1 筆 stuck row：episode `831a8c8b-...`，dispatcher 派出但 worker 從沒處理）。

## What Changes

- Worker service 跑 `--concurrency=3`（單 replica × 3 prefork worker process；實作偏離原 design「3 replicas × concurrency=1」，詳見 design.md「Worker 平行模型」）
- `transcription_queue` 表新增 `celery_task_id` 欄位（nullable string），任務開始時由 worker 寫回，供 force-cancel 透過 Celery `revoke(terminate=True, signal='SIGTERM')` 中止實際執行的任務
- 擴充 `POST /admin/queue/{id}/cancel`：新增 `force` query param（預設 false），不帶 force 時維持原行為（pending → cancel OK / running → 409）；帶 `force=true` 時 running row 也接受，呼叫 Celery revoke + 標 cancelled + 釋放 running 槽
- ~~Admin UI `max_concurrent_transcriptions` 數字輸入框 max 改 3 + 警示~~（移出 scope — 見 Non-Goals）
- ~~「轉錄序列」UI：force-cancel 按鈕、cancel 按鈕顯示邏輯~~（移出 scope — 見 Non-Goals）

## Non-Goals

- 不動 cron tick / dispatcher 的派任邏輯（dispatcher 仍只看 DB setting cap，不感知 replicas 數）
- 不改 Whisper API / local fallback 機制
- 不做 worker auto-scaling（replicas 寫死 3，不從 env 讀也不從 setting 動態算）
- Setting 上限 3 寫死在前後端（不引入 `WORKER_REPLICA_COUNT` env var），未來若要改 replicas 需同步修 code
- 不重設計排程 UI 的「下次執行時間」「執行歷史」（屬另一個未開的 change）
- 不做任何前端 UI（轉錄序列 tab、強制取消按鈕、max_concurrent input）— 實作中發現 AdminPage.jsx 尚未有「轉錄序列」rows 列表 tab，前端工作整批延後到下一個 UI change（含本 change 原列出的 force-cancel 按鈕、普通 cancel 顯示邏輯、max=3 input warning）

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `transcription-queue`: 新增 `celery_task_id` 欄位；cancel API 擴充 `force` 參數允許強制取消 running row
- `task-queue`: worker 部署改為 `--concurrency=3`（單 replica × 3 prefork process）

## Impact

- Affected specs: `transcription-queue`, `task-queue`
- Affected code:
  - Modified:
    - backend/app/models/transcription_queue.py
    - backend/app/api/admin.py
    - backend/app/workers/tasks.py
    - backend/app/workers/dispatcher.py
  - New:
    - backend/alembic/versions/<new>_add_celery_task_id_to_queue.py
- Affected infrastructure: Zeabur worker service（ID `69eb1c620da29f05f49a4e2a`）`START_COMMAND` env var 改 `--concurrency=3`
- Affected operations: prod 1 筆 stuck running row（episode `831a8c8b-...`）會在驗收階段用新 force-cancel 清掉
