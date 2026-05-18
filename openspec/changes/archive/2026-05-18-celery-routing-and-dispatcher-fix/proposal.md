## Why

EP20（Axios 集）2026-05-10 卡 9+ 小時無進展，根因是 Celery 共用 default queue + FIFO：當 R3.2 topic backfill enqueue 數百個 task 時，新進的 transcribe / 雜事 task 排在隊尾，遲遲拿不到 worker slot。同時 dispatcher 把 transcription_queue row 標 `running` 的瞬間就標（task 還在 broker 排隊），騙過 stale-detect 跟 orphan-revert，看起來「在跑」實際在等 → 兩個保護機制全失效。R3.2 backfill 完成後同類事故會反覆，必須結構性修。

## What Changes

- **拆 4 條 Celery queue**：`transcribe`、`topic`、`summary`、`control`
- **加 task message priority**：transcribe priority=9（高）、topic/summary priority=2（低），prefetch=1 保證 slot 一空優先抓 transcribe
- **單 worker 多 queue 監聽**：worker `--queues=transcribe,topic,summary,control` concurrency=6，**不拆雙 worker service**（避免 RAM 浪費）
- **task_routes + task_default_queue="control"**：新增 task 沒指定 queue 自動走 control，防遺漏
- **dispatcher 不再 set status=running**：移除 dispatcher 對 `transcription_queue.status` / `started_at` 的更新；defer 到 worker task entry
- **dispatcher 用 `dispatched_at` column + `FOR UPDATE SKIP LOCKED` 防自身 race**（B1 reviewer blocker fix）：dispatcher SELECT 排除 `dispatched_at IS NOT NULL` row、pick 後 commit `dispatched_at=NOW()` 才 `send_task`；worker entry 與 terminal transition 都 clear `dispatched_at=NULL`；startup hook 加 stuck 5min reset 規則
- **worker task 進場 idempotency check**：若 row 已 `running` 且 `started_at` 在 5 min 內 → 直接 ack 不重跑（第二道防線：防 broker 端 redeliver 同訊息）
- 不動 stale-detect / cron_tick 內部邏輯（被騙的源頭修了它就有效）
- Zeabur worker service START_COMMAND 同步加 `--queues` 參數

## Non-Goals

- **不**拆雙 worker service（已 discuss 排除：RAM 浪費 + 月費 +$3-5；priority 已能解決）
- **不**做按 task type 細粒度暫停按鈕（屬 F2 範疇）
- **不**動 LLM provider / OpenAI client / retry config（屬 F2 範疇）
- **不**改 Celery 結果後端（result backend 維持 Redis）
- **不**動 Beat schedule（cron_tick / quota_digest / db_backup 排程不變，只改它們發到 control queue）
- **不**支援 RabbitMQ broker（Redis 為唯一支援，priority_steps 只在 Redis broker 配置）

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `task-queue`: queue 從單一 default 拆成 4 條 + task_routes + message priority + task_default_queue
- `transcription-queue`: dispatcher 不再 set status=running；defer 到 worker entry；worker 加 idempotency check

## Impact

- Affected specs: `task-queue`、`transcription-queue`
- Affected code:
  - Modified:
    - `backend/app/workers/celery_app.py`（task_routes / priority_steps / task_default_queue）
    - `backend/app/workers/dispatcher.py`（移除 set running + started_at；只送 task）
    - `backend/app/workers/tasks.py`（transcribe task 進場 idempotency check + set running）
    - `backend/app/workers/topic_task.py`（priority=2 + queue 標註）
    - `backend/app/workers/summary_task.py`（priority=2 + queue 標註）
    - `backend/app/workers/cron_tick.py`（送 control queue）
    - `backend/app/workers/quota_digest.py`、`backend/app/workers/eval_reminder.py`、`backend/app/workers/db_backup.py`、`backend/app/workers/tokenizer_reload.py`（送 control queue）
    - `entrypoint.sh`（worker START_COMMAND 加 `--queues=transcribe,topic,summary,control`）
  - New:
    - `backend/tests/test_celery_routing.py`（routes / priority 行為驗證）
    - `backend/tests/test_dispatcher_idempotency.py`（worker idempotency check + B1 dispatcher race + startup stuck-detect 驗證）
    - `backend/alembic/versions/yyyy_add_transcription_queue_dispatched_at.py`（add `dispatched_at TIMESTAMPTZ NULLABLE` + partial index）
- Deploy: Zeabur worker service env / START_COMMAND 更新；4 service redeploy
