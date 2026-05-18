## Context

PodcastRAG 走 Celery + Redis broker，所有 task 預設都 enqueue 到 default queue `celery`。當前 worker `START_COMMAND=celery -A app.workers.celery_app worker --loglevel=info --concurrency=6`，沒指定 `--queues`，等同只聽 default queue。`celery_app.py` 沒設 `task_routes` / `task_queue_max_priority`。

5/10 EP20 卡 9+ 小時案例證實兩個獨立但耦合的缺陷：

1. **FIFO 共用 queue**：R3.2 backfill 一次 enqueue 323-334 個 topic task，全擠 default queue，新進的 transcribe task 排在隊尾，concurrency=6 + 每 task ~3.5 min → EP20 等 ~3 hr 才輪到 slot。
2. **Dispatcher 提前 set running**：`dispatcher.py` 在 `send_task` 後立刻 update `transcription_queue.status='running'` + `started_at=NOW()`。Celery `task_acks_late=True` + `prefetch=1` 的設定下，task 在 broker 等待時間可能很長，但 DB 看起來「在跑」→ `cron_tick` 的 stale-detect 30 min 閾值跟 `orphan-revert` 都被騙過去。

當前已存在保護機制（`deploy-resilience` change archive 2026-05-03）：worker 重啟後 1-3 min 把 `running` 但 worker 不認得的 row 推回 pending。但這只處理「worker 死掉」case，不處理「dispatcher 標 running 但 task 從沒被 worker pick」的 case。

EP20 不是個案 — R3.2 backfill 只要再跑就會再卡，未來 R3.3 / R2.1 / 任何 backfill 都會踩同一個雷。

相關 specs：`task-queue`（Celery 設定）、`transcription-queue`（dispatcher / cron_tick 行為）。

## Goals / Non-Goals

**Goals:**

- transcribe task 在最壞情境下，等待時間 ≤ 一個 topic/summary task 的執行時間（~3.5 min）
- dispatcher 不再造成 `transcription_queue.status` 跟 worker 真實狀態脫鉤
- stale-detect 跟 orphan-revert 在新模型下能真正抓到「在 broker 排隊太久」的 row
- 新增 task 預設行為安全（沒設 queue 不會被遺漏 / 不會錯排到高優先）
- 不引入新外部依賴、不增加 Zeabur 月費（單 worker 維持 4GB RAM 上限）

**Non-Goals:**

- 不拆雙 worker service（discuss 結論：priority + prefetch=1 已能解決 EP20，雙 worker 月費 +$3-5 + RAM 浪費 + 命名混亂）
- 不做按 task type 細粒度暫停 / resume button（屬 F2 範疇）
- 不動 LLM provider 客戶端、retry 邏輯、circuit breaker（屬 F2 範疇）
- 不改 Celery 結果後端（result backend 維持 Redis）
- 不改 Beat schedule cron 表達式（cron_tick / quota_digest / db_backup 排程不變）
- 不支援 RabbitMQ broker（priority_steps 配置只在 Redis broker 驗證；未來如要切 RabbitMQ 需獨立 change）

## Decisions

### Decision: 4 條 queue 分流（transcribe / topic / summary / control）

**選擇**：拆 4 條 queue 而非 2 條（transcribe vs batch）。

**理由**：

- `control` queue 隔離 cron_tick / quota_digest / db_backup / eval_reminder / tokenizer_reload / zsend 寄信等「短小但不能延遲」雜事。如果跟 batch 混在 topic queue，未來大量 backfill 仍可能延遲寄信、備份。
- `topic` 跟 `summary` 拆開保留未來彈性（譬如未來 summary backfill 也大量跑時，可能想單獨給 topic 更高 priority）。
- 4 條 queue 在 Redis broker 是 4 個 list key，效能影響可忽略（Redis O(1) push/pop）。

**替代**：拆 2 條（transcribe vs batch）— 簡單但 control 任務會被 batch 擠。

### Decision: 單 worker 多 queue + Celery message priority

**選擇**：單一 worker service `--queues=transcribe,topic,summary,control --concurrency=6`，搭配 Celery task priority。

**理由**：

- 雙 worker service 在沒 batch 時 backfill-worker 4 slot 全閒，浪費 RAM（Linode SIN 4GB 已有壓力）。
- Celery + Redis broker 支援 `task_queue_max_priority` 跟 `priority_steps`，slot 釋放時 broker 會 pop 最高 priority 訊息。
- `worker_prefetch_multiplier=1` 已設（commit `80131ba`），保證 worker 不囤積，slot 一空馬上重排序。
- 最壞等待時間 = 一個 topic/summary task 執行時間（~3.5 min）— 對 transcribe 完全可接受（80 min 長集本身要 10-15 min）。

**替代 1**：雙 worker service — 月費 +$3-5、RAM 浪費、命名混亂。

**替代 2**：單一 queue + 純 priority（不拆 queue）— 簡化但失去未來「停掉某個 queue 整批暫停」彈性，F2 斷路器要按 service 暫停會更難。

### Decision: priority 數值與 priority_steps 設計

**選擇**：

- `task_queue_max_priority=10`、`task_default_priority=5`
- `broker_transport_options={"priority_steps": [0, 3, 6, 9]}`
- transcribe = 9（高）、topic = 2（低）、summary = 2（低）、control 預設 5

**理由**：

- Redis broker 把 priority 實作為 sub-queue（每個 priority level 一個 list key），priority_steps 控制粒度。4 級 (0/3/6/9) 對應 low/default/medium/high，足夠當前需求且 Redis key 數量可控。
- transcribe=9 確保即使 control queue 有大量寄信 task，也不會擋 transcribe。
- topic/summary=2 確保 backfill 一定排在 control / transcribe 之後。

**替代**：priority_steps=[0,5,10] — 粒度太粗；priority_steps=[0,1,2,...,9] — Redis key 暴增 10 倍但無實質好處。

### Decision: dispatcher 不再 set status=running

**選擇**：dispatcher 只負責 `send_task`，移除對 `transcription_queue.status` 跟 `started_at` 的更新。`status=running` 跟 `started_at` 都改由 worker task entry 自己 update。

**理由**：

- 唯一根因修復 — dispatcher 看不到 task 是否真的被 pick，不該標 running。
- worker 自己 set running 才能保證 DB 狀態 = worker 實際狀態 → stale-detect 30 min 閾值真有意義。

**替代**：dispatcher 加超時檢查（譬如「30 min 後若 status 還是 running 但 celery_task_id 沒進展就 reset」）— 治標，仍然有 race window。

### Decision: worker task entry idempotency check

**選擇**：transcribe / topic / summary task 進場第一行：`SELECT FOR UPDATE` 撈該 row，若 `status='running'` 且 `started_at > NOW() - 5 min` → log warning + 直接 ack 不重跑；其他狀況 update `status='running'` + `started_at=NOW()` + `celery_task_id=task.request.id`。

**理由**：

- dispatcher 雖然不再 set running，但仍可能在前一輪 `cron_tick` 還在處理時連發 task（每分鐘一輪）→ broker 上同一集可能有 2 個 task。
- 5 min window：覆蓋一般 task 啟動 + 早期執行時間，避免重複跑燒錢（轉錄 80 min 集 OpenAI 一次 ~$1）。
- `SELECT FOR UPDATE` 防 concurrent task 都 pass check。

**替代**：用 Redis SETNX lock — 多一個 state store，DB 已能解決就不引入。

### Decision: dispatcher 用 dispatched_at column 防自身 race（B1 reviewer blocker）

**選擇**：在 `transcription_queue` 加 `dispatched_at TIMESTAMPTZ NULLABLE` column；dispatcher SELECT 條件改為 `status='pending' AND dispatched_at IS NULL` 用 `FOR UPDATE SKIP LOCKED`；pick 後在同 transaction set `dispatched_at=NOW()`、commit、再 `send_task`。worker 在 entry 與所有 terminal transition 都 clear `dispatched_at=NULL`。startup hook 加新規則：`status='pending' AND dispatched_at IS NOT NULL AND dispatched_at < NOW()-INTERVAL '5min'` 也要 reset。

**理由**：

- Reviewer B1 點出：dispatcher 既然不再 set `status=running`、自己就看不到上次 dispatch 過誰；下一輪 tick（每分鐘）仍會 SELECT 到同一個 pending row → 同集 broker 上會有 2+ 個 task。worker entry idempotency check 雖能擋重跑、但 broker 已被灌雙倍噪音、race window 內仍有同時跑兩份的可能（兩個 task 都看到 pending → 都 set running → 第二個被擋是靠 5min 視窗 + FOR UPDATE）。
- `dispatched_at` 是 dispatcher 自己的「memo pad」— SELECT filter 排除已 dispatch row 後，下一輪自然不會再選。
- `FOR UPDATE SKIP LOCKED` 順手解決「多 dispatcher instance」場景（rolling deploy / dispatcher 暫時雙開）。
- 5 min stuck-detect 處理 dispatcher 在 commit 完 dispatched_at 但還沒 `send_task` 就 crash 的 corner case（broker 沒收到 task、row 永遠卡 pending+dispatched_at 不 NULL）。

**替代**：

- 用 Redis SETNX 鎖 `dispatch:<row_id>` TTL 5min — 多一個 state store，DB 已能解決就不引入。
- worker idempotency check 視窗縮到 30 秒 — 治標、broker 仍會被灌噪音。
- dispatcher 改為 long-polling `LISTEN/NOTIFY` 改 push 模型 — 大改、超出本 change 範圍。

### Decision: task_default_queue="control"

**選擇**：`celery_app.conf.task_default_queue = "control"`，沒指定 queue 的 task 自動走 control。

**理由**：

- 未來新 task 開發者忘記設 queue，不會神祕地不執行（會走 control 至少有 worker 會接）。
- control 是低流量 + priority=5（中），最不傷其他 queue。

**替代**：強制每個 task 必須宣告 queue（沒宣告 raise）— 太硬，會擋住 ad-hoc enqueue。

## Risks / Trade-offs

- **Risk: priority_steps Redis 行為與 RabbitMQ 不同** → Mitigation: 在 `test_celery_routing.py` 直接驗 priority pop 順序；文件明確標註只支援 Redis broker（Non-Goals 已列）
- **Risk: dispatcher 改完之後，舊 row（status=running 但 started_at 是 dispatcher 時間）會被 worker idempotency check 誤判** → Mitigation: deploy 前先寫 migration 或 startup hook 把所有 `status=running` row 回滾成 pending（`deploy-resilience` 已有類似機制可參考）
- **Risk: worker entry 的 SELECT FOR UPDATE 增加 DB 鎖等待** → Mitigation: 鎖只持有單 row 微秒級，concurrency=6 下不會競爭
- **Risk: control queue 跟 transcribe queue priority 差距大，但 control 任務（如寄信 ZSend）有時也想優先** → Mitigation: 個別 task 可在 `apply_async` 時 override priority；control queue 預設 priority=5 已足夠
- **Trade-off: priority + prefetch=1 vs 雙 worker** → 接受最壞等待 3.5 min，換不浪費 RAM + 配置簡單

## Migration Plan

1. **Stage A — code 改完合併進 main，CI 全綠**
   - 改 8 個 worker py 檔 + entrypoint.sh + 2 個新 test
   - 本地 docker-compose 跑一輪 R3.2-style backfill 驗 priority 行為（transcribe 中途 enqueue → 立刻插隊）
2. **Stage B — Zeabur worker service env 更新**
   - START_COMMAND 加 `--queues=transcribe,topic,summary,control`（其他 service backend / dispatcher / beat 不動）
3. **Stage C — deploy + 手動驗證**
   - Push commit → Zeabur build → worker redeploy
   - 跑 startup hook 把現存 `status=running` row 回滾成 pending
   - prod inspect: `celery -A app.workers.celery_app inspect active_queues` 確認 worker 聽 4 條 queue
   - enqueue 一個 transcribe + 同時 enqueue 100 個 topic dummy task，確認 transcribe 立刻被 pick
4. **Rollback**：git revert + worker redeploy；舊 `status=running` row 不變，舊 dispatcher 仍能繼續跑（只是回到原本問題）

## Resolved Questions

- **`quota_digest` / `eval_reminder` / `db_backup` / `tokenizer_reload` 的 `apply_async` 呼叫點是否要顯式加 `queue="control"`？** → **靠 `task_routes` 自動分流**。理由：集中管理避免 queue 字串散落各檔；新 task 沒設 queue 自動走 `task_default_queue="control"` 已是安全網；強制每處顯式宣告會被改 / 漏改。
- **worker idempotency check 的 5 min window 是否需要 env 可調？** → **寫死 5 min**。理由：window 是「合理任務啟動時間」+ 「retry buffer」的物理上限，不該被外部 ops 隨便改動；要調時改 source 比改 env 更安全（會走 review）。
- **B1 reviewer blocker：dispatcher 自身 race** → 已收斂為「dispatched_at column + SELECT FOR UPDATE SKIP LOCKED + worker terminal clear + startup hook stuck-detect」四件套（見 Decision: dispatcher 用 dispatched_at column 防自身 race）。
