## 1. Celery 設定（task_routes / priority / default queue）

- [x] 1.1 在 `backend/app/workers/celery_app.py` 加入 `task_routes` 配置，把 `transcribe_episode` / `classify_episode_topics` / `generate_episode_summary` / cron_tick / quota_digest / eval_reminder / db_backup / tokenizer_reload 八個 task 對應到 `transcribe` / `topic` / `summary` / `control` 四條 queue（落實 Decision: 4 條 queue 分流（transcribe / topic / summary / control）+ Requirement: Queue routing splits tasks across four named queues）
- [x] 1.2 在 `celery_app.py` 同檔案加入 `task_default_queue="control"`、`task_queue_max_priority=10`、`task_default_priority=5`、`broker_transport_options={"priority_steps": [0, 3, 6, 9]}`（落實 Decision: priority 數值與 priority_steps 設計 + Decision: task_default_queue="control" + Decision: 單 worker 多 queue + Celery message priority + Requirement: Message priority orders task dispatch within and across queues）
- [x] 1.3 在 `tasks.py` / `topic_task.py` / `summary_task.py` 三個 task 的 `@celery_app.task` decorator 加 `priority=9`（transcribe）或 `priority=2`（topic / summary）；其他 task 維持預設 priority=5

## 2. Worker 啟動參數

- [x] 2.1 修改 `entrypoint.sh` worker 分支：當 `START_COMMAND` 模式為 worker 時，預設加 `--queues=transcribe,topic,summary,control`；保留可被 env 覆寫的彈性（落實 Requirement: Worker subscribes to all four named queues）
- [x] 2.2 更新 `docs/` 部署文件 + `CLAUDE.md` 補充新的 queue 模型 + 四條 queue 用途說明

## 3. Dispatcher 改寫

- [x] 3.1 修改 `backend/app/workers/dispatcher.py`：移除對 `transcription_queue.status` / `started_at` / `celery_task_id` 的 update，dispatcher 只負責 `send_task`（落實 Decision: dispatcher 不再 set status=running + Requirement: Dispatcher pops jobs from DB queue in FIFO order modified scenario "Dispatcher does not pre-mark row as running"）
- [x] 3.2 修改 dispatcher 的 concurrency cap 計算邏輯：改用 `transcription_queue.status='running'` 的 row count 當分母（不再依賴 dispatcher 自己 set 的 in-memory state）

## 4. Worker task 進場 idempotency

- [x] 4.1 在 `backend/app/workers/tasks.py` 的 `transcribe_episode` 開頭加入 `_claim_queue_row(episode_id, task_id)` 函式：用 `SELECT ... FOR UPDATE` 撈對應 row，依 status / started_at 決定 proceed / skip / reclaim 三種行為（落實 Decision: worker task entry idempotency check + Requirement: Worker task entry transitions queue row to running atomically，覆蓋 4 個 scenario：Pending row claimed / Duplicate within 5min skipped / Stale beyond 5min reclaimed / Cancelled row acked）
- [x] 4.2 把同樣的 entry 模式複製到 `topic_task.py` 與 `summary_task.py`（雖然 spec 主要針對 transcribe，但 topic / summary 也可能因 chain race 出現重複 task；防禦性加上）

## 5. Startup hook 擴充

- [x] 5.1 在現有 worker startup self-recovery 路徑（`backend/app/workers/lifecycle.py` 或 `cron_tick.py` 對應位置）加入新規則：reset `status='running' AND started_at IS NULL` 的 row 回 pending 並 release throttle slot（落實 Requirement: Startup hook resets dispatcher-marked running rows to pending）

## 6. 測試

- [x] 6.1 新增 `backend/tests/test_celery_routing.py`：assert `celery_app.conf.task_routes` 把四個 task 各自送到對應 queue，並 assert `task_default_queue == 'control'`（Requirement: Queue routing scenarios）
- [x] 6.2 在 `test_celery_routing.py` 同檔加 priority pop 順序測試：用 in-memory broker 或 Redis fixture enqueue priority=9 / 5 / 2 task 各一，consumer pop 順序須是 9 → 5 → 2（Requirement: Message priority pop order example）
- [x] 6.3 新增 `backend/tests/test_dispatcher_idempotency.py`：覆蓋 worker entry 4 個 scenario（pending claimed / duplicate within 5min / stale reclaimed / cancelled acked）+ dispatcher 不 pre-mark scenario
- [x] 6.4 跑 `pytest backend/tests/` 全部，確認 throttle / per-show lock / graceful shutdown / orphan-revert 既有測試不退步（Requirement: Existing tests for queue behaviour SHALL pass without regression）

## 7. 部署 + 驗證

- [ ] 7.1 commit + push main → CI 全綠 → Zeabur 4 service rebuild redeploy（worker / backend / dispatcher / beat）
- [ ] 7.2 用 zeabur exec 跑 `celery -A app.workers.celery_app inspect active_queues` 確認 worker 真的訂閱了 transcribe / topic / summary / control 四條 queue
- [ ] 7.3 prod 煙測：手動觸發一個 transcribe + 同時 enqueue 100 個 topic dummy task，觀察 transcribe 是否在 ~3.5 min 內被 pick（不是排在 100 個 topic 後面）
- [ ] 7.4 EP20 case study 收尾：在 `docs/case-studies/ep20-transcribe-blocked-by-topic-backfill.md` 標註此 change archive 後 root cause 已根治；release log 補對應 entry
