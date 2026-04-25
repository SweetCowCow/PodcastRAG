## 1. 組態

- [x] 1.1 實作 Requirement: MAX_CONCURRENT_TRANSCRIPTIONS is a backend setting——在 `backend/app/core/config.py` 的 `Settings` class 新增 `max_concurrent_transcriptions: int = 1` 欄位（Pydantic 自動從 env `MAX_CONCURRENT_TRANSCRIPTIONS` 讀取）
- [x] 1.2 在 Zeabur Dashboard 對 backend service (`69eb10360da29f05f49a4b0b`) 與 worker service (`69eb1c620da29f05f49a4e2a`) 各設 `MAX_CONCURRENT_TRANSCRIPTIONS=1` env var（或先保留預設，於驗證階段再設）

## 2. 後端：throttle helpers

- [x] 2.1 實作 Requirement: Global concurrency semaphore bounds active transcriptions + Per-show exclusivity lock + Global slot key has a TTL safety net——新增 `backend/app/workers/throttle.py` 檔案，內容：
  - 匯入 `redis` sync client（Celery task 是 sync 函式，用 sync redis client 最直接；從 `settings.celery_broker_url` 解析出 Redis connection）
  - 實作 `_get_redis()` 函式（lru_cache）回傳 `redis.Redis.from_url(settings.celery_broker_url)`
  - 實作 `acquire_global_slot(task_id: str, max_concurrent: int) -> bool`：`INCR transcribe:global:active_count` → 若 `> max_concurrent` 立即 `DECR` 還回去 return False；否則 `SET transcribe:global:slot:{task_id} 1 EX 7200` return True
  - 實作 `release_global_slot(task_id: str) -> None`：`DECR transcribe:global:active_count`；再 `SET transcribe:global:active_count 0 XX` 若值變成負數（clamp 為 0，透過 `GET` + `SET ... XX` 檢查，或 Lua script atomic clamp）；`DEL transcribe:global:slot:{task_id}`
  - 實作 `acquire_show_lock(show_id: str) -> bool`：`SET transcribe:show:{show_id}:lock 1 NX EX 1800`；回傳是否 acquire 成功
  - 實作 `release_show_lock(show_id: str) -> None`：`DEL transcribe:show:{show_id}:lock`
- [x] 2.2 在 `backend/app/workers/throttle.py` 加 constants：`GLOBAL_ACTIVE_KEY = "transcribe:global:active_count"`、`GLOBAL_SLOT_KEY = "transcribe:global:slot:{}"`、`SHOW_LOCK_KEY = "transcribe:show:{}:lock"`、`GLOBAL_SLOT_TTL = 7200`、`SHOW_LOCK_TTL = 1800`

## 3. 後端：tasks.py 改寫

- [x] 3.1 實作 Requirement: Transient errors trigger automatic retry with exponential backoff + Permanent errors bypass retry and mark transcript failed——在 `backend/app/workers/tasks.py` 頂端新增 imports：`httpx`、`openai`、`pydub.exceptions`、`from app.core.config import settings`、`from app.workers.throttle import (acquire_global_slot, release_global_slot, acquire_show_lock, release_show_lock)`
- [x] 3.2 定義 `TRANSIENT_ERRORS = (httpx.HTTPError, httpx.TimeoutException, openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError, asyncio.TimeoutError, ConnectionError)` 和 `PERMANENT_ERRORS = (RssParseError, StorageError, FileNotFoundError, pydub.exceptions.CouldntDecodeError, openai.AuthenticationError, openai.BadRequestError)`（需先確認 import 這些 class，若 services.storage 無 StorageError 可引用，或改為 catch `Exception` 的子 match）
- [x] 3.3 修改 `@celery_app.task(name="app.workers.tasks.transcribe_episode", bind=True)` 為 `@celery_app.task(name="app.workers.tasks.transcribe_episode", bind=True, autoretry_for=TRANSIENT_ERRORS, max_retries=3, retry_backoff=True, retry_backoff_max=300, retry_jitter=True)`
- [x] 3.4 在 `transcribe_episode` task 函式 body 最外層包上 throttle 邏輯：
  - 開頭：`max_c = settings.max_concurrent_transcriptions`；若 `not acquire_global_slot(self.request.id, max_c)` → `raise self.retry(countdown=15, max_retries=None)`
  - 接著 `self._acquired_global = True`；`if not acquire_show_lock(str(ep_uuid_from_payload.show_id))`... 要先拿到 show_id（可從 DB 查 episode 或在 enqueue 時傳入；簡化：先 query episode 拿 show_id 再判斷）→ `release_global_slot(self.request.id)`；`raise self.retry(countdown=60, max_retries=None)`
  - 接下來是既有的 `_run(episode_id)` 邏輯；包在 `try: ... except PERMANENT_ERRORS as exc: 寫 failed + return; except Exception: raise（讓 autoretry_for 處理 transient）finally: release_show_lock(show_id); release_global_slot(self.request.id)`
  - 注意：show_id 需在 try 之外就取得以便 finally 釋放（預先 query 一次）
- [x] 3.5 `ERROR_MESSAGE_MAX_LEN` 既有，permanent 分支沿用截斷邏輯

## 4. 後端：queue-status 端點

- [x] 4.1 實作 Requirement: Queue status endpoint reports live transcription throughput——在 `backend/app/schemas/admin.py` 新增 `QueueStatusResponse(BaseModel)`：`active: int`、`pending_in_queue: int`、`pending_in_db: int`、`max_concurrent: int`
- [x] 4.2 在 `backend/app/api/admin.py` 新增 `GET /admin/queue-status` handler：
  - 用 throttle._get_redis() 讀 `transcribe:global:active_count`（`int(redis.get(key) or 0)`）
  - 讀 `redis.llen("celery")` 當 `pending_in_queue`
  - `await db.scalar(select(func.count(Transcript.id)).where(Transcript.status == TranscriptStatus.pending))` 當 `pending_in_db`
  - `settings.max_concurrent_transcriptions` 當 `max_concurrent`
  - 回 `QueueStatusResponse`

## 5. 前端：Queue status badge

- [x] 5.1 實作 Requirement: ScheduleTab shows live queue status——在 `src/AdminPage.jsx` 的 `ScheduleTab` 元件新增 state：`const [queueStatus, setQueueStatus] = React.useState(null)`
- [x] 5.2 新增 `fetchQueueStatus` callback：`fetch(\`${API_BASE}/admin/queue-status\`)` → `setQueueStatus(await res.json())`；失敗靜默（不影響主 UI）
- [x] 5.3 在 mount `useEffect` 同時：`fetchQueueStatus()` 一次 + `const id = setInterval(fetchQueueStatus, 30000)` + cleanup 時 `clearInterval(id)`
- [x] 5.4 在 ScheduleTab 頂部的 `<p>設定各節目...` 旁（或隔行）渲染 `{queueStatus && (<div>🟢 執行中 {queueStatus.active}/{queueStatus.max_concurrent}　⏳ 佇列中 {queueStatus.pending_in_queue}</div>)}`；中英對照：zh「執行中/佇列中」、en「Active/Queued」

## 6. 驗證

- [x] 6.1 本地 docker compose 跑起來，從 backend 容器 exec python 檢查 `from app.workers.throttle import _get_redis; r=_get_redis(); print(r.ping())` 回 True
- [x] 6.2 觸發一集轉錄（`POST /episodes/{id}/transcribe`），worker log 可看到 task 正常完成；事後 `redis-cli GET transcribe:global:active_count` 回 0；`redis-cli KEYS transcribe:global:slot:*` 為空
- [x] 6.3 在本機暫時設 `MAX_CONCURRENT_TRANSCRIPTIONS=1`（worker env），同時觸發兩集；觀察第二集 worker log 顯示「retrying in ~15s」，等第一集轉完第二集開始
- [x] 6.4 觸發同一 show 兩集：第二集 log 顯示「retrying in ~60s」，等第一集完成 lock 釋放後第二集開始
- [x] 6.5 模擬 permanent error：手動把某 episode audio_url 改成壞 URL 讓 pydub 抛 CouldntDecodeError，觀察 transcript.status='failed' + error_message 非空；`retries` 次數為 0（未重試）
- [x] 6.6 `curl http://localhost:8000/admin/queue-status` 回 JSON 含四個欄位數字合理
- [x] 6.7 瀏覽器後台轉錄排程頁面頂部可看到「執行中 X/Y 佇列中 Z」；觸發轉錄後 30 秒內數字會更新；切到其他 tab DevTools 可見 fetch 停止
