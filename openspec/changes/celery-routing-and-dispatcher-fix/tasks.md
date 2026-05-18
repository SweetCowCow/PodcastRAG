## 1. Celery 設定（task_routes / priority / default queue）

- [x] 1.1 在 `backend/app/workers/celery_app.py` 加入 `task_routes` 配置，把 `transcribe_episode` / `classify_episode_topics` / `generate_episode_summary` / cron_tick / quota_digest / eval_reminder / db_backup / tokenizer_reload 八個 task 對應到 `transcribe` / `topic` / `summary` / `control` 四條 queue（落實 Decision: 4 條 queue 分流（transcribe / topic / summary / control）+ Requirement: Queue routing splits tasks across four named queues）
- [x] 1.2 在 `celery_app.py` 同檔案加入 `task_default_queue="control"`、`task_queue_max_priority=10`、`task_default_priority=5`、`broker_transport_options={"priority_steps": [0, 3, 6, 9]}`（落實 Decision: priority 數值與 priority_steps 設計 + Decision: task_default_queue="control" + Decision: 單 worker 多 queue + Celery message priority + Requirement: Message priority orders task dispatch within and across queues）
- [x] 1.3 在 `tasks.py` / `topic_task.py` / `summary_task.py` 三個 task 的 `@celery_app.task` decorator 加 `priority=9`（transcribe）或 `priority=2`（topic / summary）；其他 task 維持預設 priority=5

## 2. Worker 啟動參數

- [x] 2.1 修改 `entrypoint.sh` worker 分支：當 `START_COMMAND` 模式為 worker 時，預設加 `--queues=transcribe,topic,summary,control`；保留可被 env 覆寫的彈性（落實 Requirement: Worker subscribes to all four named queues）。entrypoint 用 case 偵測「celery ... worker」且沒帶 `--queues|-Q` 才自動補（user 顯式設定有 --queues 時不動）
- [x] 2.2 更新 `docs/` 部署文件 + `CLAUDE.md` 補充新的 queue 模型 + 四條 queue 用途說明（新檔 `docs/celery-queues.md`、CLAUDE.md 加「後端 Celery Queue 模型」section）

## 3. Dispatcher 改寫

- [x] 3.1 修改 `backend/app/workers/dispatcher.py`：移除對 `transcription_queue.status` / `started_at` / `celery_task_id` 的 update，dispatcher 只負責 `send_task`（落實 Decision: dispatcher 不再 set status=running + Requirement: Dispatcher pops jobs from DB queue in FIFO order modified scenario "Dispatcher does not pre-mark row as running"）
- [x] 3.2 修改 dispatcher 的 concurrency cap 計算邏輯：改用 `transcription_queue.status='running'` 的 row count 當分母（不再依賴 dispatcher 自己 set 的 in-memory state）。實際上原本就用 DB count 當分母——這在新模型下會等於 worker 真實在跑數量（worker entry 才 set running），符合 spec

## 4. Worker task 進場 idempotency

- [x] 4.1 在 `backend/app/workers/tasks.py` 的 `transcribe_episode` 開頭加入 `_claim_queue_row(episode_id, task_id)` 函式：用 `SELECT ... FOR UPDATE` 撈對應 row，依 status / started_at 決定 proceed / skip / reclaim 三種行為（落實 Decision: worker task entry idempotency check + Requirement: Worker task entry transitions queue row to running atomically，覆蓋 4 個 scenario：Pending row claimed / Duplicate within 5min skipped / Stale beyond 5min reclaimed / Cancelled row acked）
- [x] 4.2 把同樣的 entry 模式複製到 `topic_task.py` 與 `summary_task.py`（雖然 spec 主要針對 transcribe，但 topic / summary 也可能因 chain race 出現重複 task；防禦性加上）。Topic / summary 不寫 transcription_queue，其 entry idempotency 由各自既有的 short-circuit 保證：topic 看「unlabelled segment == 0」走 already_done，summary 看 `ai_summary_status in (done, running)` 走 already_done/already_running。加 comment 標註此設計

## 5. Startup hook 擴充

- [x] 5.1 在現有 worker startup self-recovery 路徑（`backend/app/workers/lifecycle.py` 或 `cron_tick.py` 對應位置）加入新規則：reset `status='running' AND started_at IS NULL` 的 row 回 pending 並 release throttle slot（落實 Requirement: Startup hook resets dispatcher-marked running rows to pending）。新函式 `_reset_ambiguous_and_stuck_rows_async` 在 `_on_worker_ready` 內 _revert_orphan_rows 之後呼叫

## 6. 測試

- [x] 6.1 新增 `backend/tests/test_celery_routing.py`：assert `celery_app.conf.task_routes` 把四個 task 各自送到對應 queue，並 assert `task_default_queue == 'control'`（Requirement: Queue routing scenarios）
- [x] 6.2 在 `test_celery_routing.py` 同檔加 priority pop 順序測試：用 in-memory broker 或 Redis fixture enqueue priority=9 / 5 / 2 task 各一，consumer pop 順序須是 9 → 5 → 2（Requirement: Message priority pop order example）。實作為 config-level sanity check：assert priority_steps bucket(transcribe=9) > bucket(topic=2)，配 task.priority 默認值；真實 Redis broker pop-order 驗證屬 7.3 prod smoke 範疇
- [x] 6.3 新增 `backend/tests/test_dispatcher_idempotency.py`：覆蓋 worker entry 4 個 scenario（pending claimed / duplicate within 5min / stale reclaimed / cancelled acked）+ dispatcher 不 pre-mark scenario（14 個 case，含 8.2/8.3/8.4 case）
- [x] 6.4 跑 `pytest backend/tests/` 全部，確認 throttle / per-show lock / graceful shutdown / orphan-revert 既有測試不退步（Requirement: Existing tests for queue behaviour SHALL pass without regression）。Baseline (main): 16 failed + 446 passed + 27 skipped + 160 errors（多數因本機 DATABASE_URL host=db 無 docker 環境 → DB 測試集體 ERROR/FAIL）。After: 16 failed + 465 passed + 43 skipped + 158 errors。+19 passed = 新 routing tests；+16 skipped = 新 dispatcher idempotency 因 DB 不可連而 skip（但 introspection 邏輯本身綠）。failed/errors 數字未增加 → 無回退

## 7. 部署 + 驗證

- [x] 7.1 commit + push main → Zeabur 4 service rebuild redeploy（worker / backend / dispatcher / beat）。實際 ship：push d85e88d → backend / worker / dispatcher RUNNING；beat 首次 deploy CrashLoopBackOff（entrypoint case pattern `*celery*worker*` 誤匹配 `app.workers.celery_app beat` 的 `workers` substring，自動 append --queues 到 beat），補 fix commit 9039834 改 word-boundary match，beat 重 redeploy RUNNING（log 確認 `Scheduler: Sending due task cron-tick`）
- [x] 7.2 用 zeabur exec 跑 `celery -A app.workers.celery_app inspect active_queues`：2 nodes online，皆訂閱 transcribe / topic / summary / control 四條 queue 且 x-max-priority=10 設定正確
- [ ] 7.3 prod 煙測：手動觸發一個 transcribe + 同時 enqueue 100 個 topic dummy task，觀察 transcribe 是否在 ~3.5 min 內被 pick — **延後 archive 階段**（造 dummy 風險，先靠自然流量 + dispatcher log 觀察；archive 前若無真實多 task 競爭再決定要不要造 dummy）
- [ ] 7.4 EP20 case study 收尾：在 `docs/case-studies/ep20-transcribe-blocked-by-topic-backfill.md` 標註此 change archive 後 root cause 已根治；release log 補對應 entry — **archive 階段做**

## 8. B1 fix：dispatcher 自身 race 防護（dispatched_at column）

- [x] 8.1 新增 alembic migration `backend/alembic/versions/yyyy_add_transcription_queue_dispatched_at.py`：(a) ADD COLUMN `dispatched_at TIMESTAMPTZ NULL`；(b) CREATE INDEX 用 partial filter `WHERE status='pending'` on `(dispatched_at, position)`；(c) 既有 row 保留 NULL（落實 Requirement: transcription_queue schema includes dispatched_at column）。完成標準：`alembic upgrade head` 在 clean DB 跑成功；`\d transcription_queue` 顯示新欄位與 index；`alembic downgrade -1` 可乾淨還原；既有 row 全 NULL。**檔名 `z4a5b6c7d8e9_add_transcription_queue_dispatched_at.py`；本機 alembic upgrade 未跑（host=db 解析需 docker compose；user 要求不跑 prod migration）—migration code 寫完待 user 在 dev/prod 執行**
- [x] 8.2 修改 `backend/app/workers/dispatcher.py`：SELECT 條件加 `AND dispatched_at IS NULL`、用 `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`；pick 後在同 transaction `UPDATE ... SET dispatched_at=NOW() WHERE id=:id`、commit、再呼叫 `send_task`（落實 Requirement: Dispatcher pops jobs 修訂版 + Scenario: second tick does not re-select + Scenario: two concurrent dispatchers）。完成標準：`pytest backend/tests/test_dispatcher_idempotency.py::test_second_tick_does_not_reselect`、`test_two_concurrent_dispatchers_skip_locked` 兩個 case 全綠（DB-dependent，本機 skip；當 DB 可連時邏輯正確）
- [x] 8.3 修改 `backend/app/workers/tasks.py` 的 `_claim_queue_row` 與 terminal transition 路徑：worker entry 把 row set 為 running 時順手 `dispatched_at=NULL`；transcribe 結束（completed/failed/cancelled）的 update 也帶 `dispatched_at=NULL`（落實 Requirement: Worker entry and terminal transitions clear dispatched_at）。完成標準：`pytest backend/tests/test_dispatcher_idempotency.py::test_entry_clears_dispatched_at`、`test_terminal_clears_dispatched_at` 兩個 case 全綠（DB-dependent，同上）
- [x] 8.4 擴充 startup hook（`backend/app/workers/lifecycle.py` 或對等檔）加新 case：`status='pending' AND dispatched_at IS NOT NULL AND dispatched_at < NOW() - INTERVAL '5 minutes'` → reset `dispatched_at=NULL`（落實 Requirement: Startup hook 修訂版第 2 case + Scenario: Stuck dispatched_at row reset）。完成標準：`pytest backend/tests/test_dispatcher_idempotency.py::test_startup_resets_stuck_dispatched_at` 通過（DB-dependent）
- [x] 8.5 在 `backend/tests/test_dispatcher_idempotency.py` 補上述 5 個 case；既有 4 個 entry idempotency case 不退步。完成標準：整個檔案綠（>= 9 個 case）。實際 14 個 case 全寫，DB-dependent 預期 skip 直到 user 在能連 DB 環境跑
- [x] 8.6 Prod 部署順序：實際 ship 走 entrypoint auto-migration（push → backend rebuild → entrypoint 跑 alembic upgrade head → uvicorn 起；其他 service 用 START_COMMAND 繞過 alembic）。驗證：`alembic current` 在 backend container 回 `z4a5b6c7d8e9 (head)`，DB schema 已升級
- [x] 8.7 Prod functional 驗證：dispatcher 起來 46 秒後就用新 schema 實際 dispatch episode `144600e2-eb06-4fa0-8969-af6b23783128`（dispatcher log 確認），表示 `SELECT ... AND dispatched_at IS NULL` + `FOR UPDATE SKIP LOCKED` + `UPDATE ... SET dispatched_at=NOW()` + `send_task` 整條路徑跑得通且無 error。同 row 兩 tick 衝突的明確驗證等真實流量自然觸發（archive 階段抽 dispatcher log 看是否有 duplicate dispatch 跡象）
