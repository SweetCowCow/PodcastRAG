## Why

目前 `transcribe_episode` Celery 任務存在兩個系統穩定性問題：

1. **無自動重試**——任何 transient 錯誤（OpenAI API 5xx、短暫網路中斷、rate limit 429、Zeabur registry 掉包造成的 TimeoutError）都會直接把 `transcript.status` 寫成 `failed`，人工介入重跑才行。使用者看到 failed 無從判斷是永久錯誤還是暫時性錯誤
2. **無同時執行上限**——使用者若按「同步所有」、或啟用排程的節目同時有多集 pending，Celery worker 會一次拉多個任務並行跑（雖然 `worker_prefetch_multiplier=1` + `--concurrency=1` 先擋了一層，但若未來調高 concurrency 或開多個 worker pod 就會超載）。4GB RAM VPS 若同時轉錄 2+ 集可能 OOM；OpenAI Whisper API 若同時送多檔也可能撞 rate limit

另外使用者在後台看不到「目前幾集在轉、幾集在排隊」，不知道「立刻執行」到底排了什麼任務。

## What Changes

### 後端：自動重試（`backend/app/workers/tasks.py`）

- `@celery_app.task` decorator 加上：
  - `autoretry_for=(httpx.HTTPError, httpx.TimeoutException, openai.RateLimitError, openai.APIConnectionError, asyncio.TimeoutError)`
  - `max_retries=3`
  - `retry_backoff=True`、`retry_backoff_max=300`、`retry_jitter=True`（產生 10s → 60s → 300s 附隨機抖動的延遲）
- **Permanent 錯誤**（不重試，直接把 transcript 標 failed）：`RssParseError`、`StorageError`（R2 固定錯誤如 AccessDenied、404）、`FileNotFoundError`、任何 `ValueError` 從 audio 轉檔 pydub 拋出
- Permanent 錯誤處理：在 task body 的 try/except 中 catch 這些類型，寫 `transcript.status = failed`、`error_message`（截取前 ERROR_MESSAGE_MAX_LEN 字元），commit；return failure dict 讓 Celery 視為成功完成（不再 retry）

### 後端：全域並發限制（`backend/app/workers/throttle.py` 新檔）

- 實作 `acquire_global_slot()` / `release_global_slot()`：
  - Redis key `transcribe:global:active_count`（INT counter）
  - `acquire`：`INCR active_count`，若 > `MAX_CONCURRENT_TRANSCRIPTIONS`（env var，預設 `1`），馬上 `DECR` 把回去然後 return False
  - `release`：`DECR`，下限 clamp 0
- Task 開頭呼叫 `acquire_global_slot()`，拿不到用 `self.retry(countdown=15, max_retries=None)`（不算 autoretry 配額，就是排隊等）
- Task 結束（成功或 permanent failure）一定呼叫 `release_global_slot()`；放在 `finally`

### 後端：單節目節流（同檔）

- 實作 `acquire_show_lock(show_id)` / `release_show_lock(show_id)`：
  - Redis key `transcribe:show:{show_id}:lock`
  - `acquire`：`SET key 1 NX EX 1800`（1800s = 30 分鐘 max lock，避免 worker crash 後永久卡住）
  - `release`：`DEL key`
- Task 在 global_slot 之後檢查 show_lock；拿不到同樣 `self.retry(countdown=60)` 排隊
- `finally` 釋放（含 global 與 show 雙鎖）

### 後端：Queue status 端點（`backend/app/api/admin.py`）

- 新增 `GET /admin/queue-status`：
  - 讀 Redis `transcribe:global:active_count`
  - 從 DB `SELECT COUNT(*) FROM transcripts WHERE status = 'pending'`
  - 可從 Redis `LLEN celery` (Celery broker queue 長度) 取得 broker 中未 claim 的任務數
  - 回 `{ active: int, pending_in_queue: int, pending_in_db: int, max_concurrent: int }`
  - `active` = 正在執行中（有 global_slot）
  - `pending_in_queue` = broker 裡等 worker claim 的
  - `pending_in_db` = transcripts 表 status=pending 總數（含 active + queued）
  - `max_concurrent` = 當前 env MAX_CONCURRENT_TRANSCRIPTIONS 值

### 前端：Queue status panel（`src/AdminPage.jsx` ScheduleTab）

- ScheduleTab 頂部（「設定各節目的自動轉錄排程」那行旁邊）加一個 badge 列：
  - `🟢 執行中: N / M   ⏳ 佇列中: K`
  - N = active、M = max_concurrent、K = pending_in_queue
- 掛載時 fetch，並設 30 秒 polling interval
- 切離頁面時 clear interval（React.useEffect cleanup）

### 組態（`backend/app/core/config.py`）

- 新增 `max_concurrent_transcriptions: int = 1`（env `MAX_CONCURRENT_TRANSCRIPTIONS`）
- 部署到 Zeabur 時需要在 backend 與 worker 兩個 service 都設此 env var

## Non-Goals

- **不改 per-episode 錯誤詳情顯示**——errored transcript 的詳細錯誤訊息 + failed 列表 UI 屬 Change C `transcription-progress-visibility`
- **不做真正的 Celery Beat 排程執行**——排程仍是使用者偏好紀錄，實際 cron trigger 是未來功能
- **不做優先序 queue**（FIFO 就好，不考慮 priority lane）
- **不改 Celery worker `--concurrency`**（保留 worker-level 的 1，避免同 pod 平行；Redis semaphore 是 cross-pod level 的第二道保險絲）

## Capabilities

### New Capabilities

（無——本 change 的行為屬於既有 `task-queue`、`transcription-pipeline`、`admin-show-management-ui` 的擴充）

### Modified Capabilities

- `task-queue`：Celery task 加 autoretry 規則、全域 semaphore、per-show lock
- `transcription-pipeline`：`transcribe_episode` task 的錯誤分類（transient vs permanent）與重試行為
- `admin-show-management-ui`：ScheduleTab 頂部顯示 queue status

## Impact

- Affected specs: task-queue, transcription-pipeline, admin-show-management-ui
- Affected code:
  - New:
    - backend/app/workers/throttle.py（Redis semaphore + per-show lock helpers）
  - Modified:
    - backend/app/workers/tasks.py（autoretry_for、throttle acquire/release、permanent error handling）
    - backend/app/core/config.py（max_concurrent_transcriptions 設定）
    - backend/app/api/admin.py（GET /admin/queue-status 端點）
    - backend/app/schemas/admin.py（QueueStatusResponse Pydantic schema）
    - src/AdminPage.jsx（ScheduleTab 頂部顯示 badge、polling）
  - Removed:（無）
