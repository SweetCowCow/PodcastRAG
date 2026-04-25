## Context

目前 `backend/app/workers/tasks.py::transcribe_episode` Celery task 在遇到任何例外就把 `transcript.status` 設成 `failed`、清空 `audio_storage_key`、寫 error_message 並 return。沒有 retry、沒有 throttle。部署在 Linode SIN 4GB RAM + 2 vCPU VPS，單一 worker pod `--concurrency=1`。broker 是 Redis（單 instance）。Change B1 會讓使用者能用「立刻執行」和「同步所有」一次塞多個任務進 queue，對並發控制需求拉高。

## Goals / Non-Goals

**Goals:**

- Transient 錯誤（網路 blip、OpenAI 5xx/429、httpx timeout）自動指數 backoff 重試（10s/60s/300s），最多 3 次
- 同時最多 N 集轉錄（`MAX_CONCURRENT_TRANSCRIPTIONS` 預設 1），cross-pod enforceable（未來 scale 到 2 worker pod 仍成立）
- 同一 show 同時最多 1 集轉錄（避免單一節目佔滿 queue）
- worker crash 時 semaphore / lock 不會永久卡死（都有 TTL）
- 使用者看得到 queue 深度（執行中 N、等待 M）

**Non-Goals:**

- 不處理 priority queue（FIFO 就好）
- 不保證 100% 精準計數（semaphore 允許短暫 +1 誤差在可接受範圍）
- 不做 per-episode UI 錯誤詳情（Change C）
- 不做 Celery Beat 真正 cron（仍是使用者偏好紀錄）

## Decisions

### 錯誤分類：transient vs permanent

Transient（autoretry，指數 backoff）：
- `httpx.HTTPError`、`httpx.TimeoutException`（RSS 抓取、OpenAI API 連線）
- `openai.RateLimitError`、`openai.APIConnectionError`、`openai.APITimeoutError`
- `asyncio.TimeoutError`
- `ConnectionError`

Permanent（直接 status=failed）：
- `RssParseError`（feed 本身壞掉）
- `StorageError`（R2 固定錯誤：AccessDenied、bucket 不存在）
- `FileNotFoundError`（本地檔案不見，狀態異常）
- `pydub.exceptions.CouldntDecodeError`（音檔無法解碼）
- `openai.AuthenticationError`（api key 錯，retry 沒用）
- `openai.BadRequestError`（audio 格式拒收）

**理由**：autoretry 對 transient 有效（下次試成功率高）；對 permanent 無用且浪費 quota。Celery 的 `autoretry_for=(transient_tuple)` + try/except permanent 的寫法讓兩類並存。

### Alternative 考慮過：全部都 retry

若全部 retry（包含 permanent），會浪費 worker 時間 + OpenAI 配額在注定失敗的任務上，還會把 queue 塞住。不採用。

### 全域並發：Redis INCR/DECR counter（非 Redlock）

**設計**：
- Key：`transcribe:global:active_count`（普通 int counter）
- Acquire：`INCR active_count`；讀結果，若 > max，`DECR` 還回去，return False
- Release：`DECR active_count`；後置 clamp（`SET active_count 0 XX` if 負數）
- 無 TTL on counter 本身（counter 是 long-lived state，不是 lock）

**為什麼不用 Redlock**：Redlock 解決 distributed mutex 的問題（需要多 Redis instance 才安全），我們只有一個 Redis，INCR 是 atomic，夠用。

**Worker crash 處理**：worker 在 acquire 之後還沒 release 就掛了 → counter 會少 DECR 一次，變成假值。為防止這種洩漏：
1. 每個 slot acquire 時同時 `SET transcribe:global:slot:{task_id} 1 EX 7200`（2 小時 TTL，遠大於正常 task 時間）
2. Release 時 `DEL transcribe:global:slot:{task_id}`
3. 每 5 分鐘 worker startup / heartbeat 跑一次 reconcile：`SCAN transcribe:global:slot:*` 得實際 slot 數，若 counter 與實際不符用 `SET active_count <actual> XX` 對齊

為了本 change 範圍聚焦，第一版先只做 1+2（slot key 帶 TTL），不做 3（reconcile）。若觀察到長期漂移再加。

### Per-show lock：SET NX EX

- Key：`transcribe:show:{show_id}:lock`
- Acquire：`SET key 1 NX EX 1800`（30 分鐘 TTL，夠一集長 podcast 轉完；避免 worker 掛了永久卡死）
- Release：`DEL key`
- 拿不到：`self.retry(countdown=60)`（不算 max_retries 配額）

30 分鐘 TTL 的選擇：目前 OpenAI Whisper API 對 25MB audio 約 1-2 分鐘處理；4 小時的 podcast chunking + 多次 API call 最糟也不超過 25 分鐘。30 分鐘給足 margin。

### Queue status 資料來源

- `active`（執行中）：Redis `GET transcribe:global:active_count`
- `pending_in_queue`（broker 中未 claim）：Redis `LLEN celery`（預設 queue 名）
- `pending_in_db`（DB 中 status=pending 總數）：DB count
- `max_concurrent`：`settings.max_concurrent_transcriptions`

**pending_in_db 可能 > active + pending_in_queue**：若 transcript 之前 status=pending 但 Celery task 已消耗掉（例如重複 enqueue 的情況），這是 edge case 可接受。

### Retry 與 throttle 的互動

- `autoretry_for` 的 retry（transient error）→ 會重新 ack 回 broker → 下次 worker pick up 時重新走 acquire flow
- `self.retry(countdown=...)` 的 throttle retry → 同樣重新 ack 回 broker
- 兩者共用 max_retries 配額？**不共用**。`autoretry_for` 用 task 級 max_retries=3；`self.retry(countdown=15, max_retries=None)` 明確指定 None，不消耗配額
- 這意味 transient + throttle 混合情境下 task 最多可能 retry 很多次（throttle 不設限），接受

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Worker crash 造成 counter 漂移 | slot key 加 TTL (2h)；未來加 reconcile loop |
| Per-show lock 鎖定後 worker 掛了 → show 最多 30 分鐘無法轉 | 30 分鐘後 Redis TTL 自動釋放；實務上 worker crash 罕見 |
| `self.retry(countdown=60, max_retries=None)` 造成無限 retry | Broker 若持續滿載，queue 深度會爆；監控 `pending_in_db` 超過閾值時人工介入（未來加 alert）|
| 兩個 retry 機制（autoretry + self.retry）共存使 task state machine 複雜 | 用清楚的 try/except 結構分隔（先 throttle acquire → 再 core logic try/except transient → finally release）|
| `INCR then DECR if over limit` 有短暫超標窗口 | 短暫超標 1 個 slot 可接受；不是 hard safety，是壓力控制 |

## Migration Plan

1. 部署 B2 前，Zeabur backend 與 worker 兩個 service 都設 `MAX_CONCURRENT_TRANSCRIPTIONS=1`（env var）
2. Redis 中 `transcribe:global:active_count` 初始無值 → 首次 INCR 變 1 → OK
3. 若部署前已有 transcripts status=pending 且無 active task（之前 crashed），新 throttle 不會影響——它們被 Celery 重啟重跑時會走新流程
4. Rollback：移除 task autoretry + throttle call、回退 tasks.py。slot keys 最多 2 小時後自動過期，不需要人工清
5. 觀測：部署後監看 `/admin/queue-status`，若 `active` 長期 > 0 而 `pending_in_db` 堆積，表示 worker 堵塞，看 Celery log

## Open Questions

（無——決策已明確）
