## 1. 資料層：新增與擴充 schema

- [x] 1.1 To satisfy "DB-backed transcription queue table": 在 `backend/app/models/transcription_queue.py` 新增 SQLAlchemy model `TranscriptionQueue`，欄位依 spec：`id` (UUID PK, default uuid4)、`episode_id` (UUID FK to episodes.id, UNIQUE)、`show_id` (UUID FK to shows.id)、`status` (Enum `pending`/`running`/`completed`/`failed`/`cancelled`, default `pending`)、`position` (Integer)、`enqueued_at` (DateTime UTC, default now)、`started_at` (DateTime nullable)、`finished_at` (DateTime nullable)、`error_message` (Text nullable)、`ignored` (Boolean default false)、`whisper_model` (String 50)。在 `backend/app/models/__init__.py` 註冊
- [x] 1.2 To satisfy "DB-backed transcription queue table": 在 `backend/alembic/versions/` 新增 migration 檔建立 `transcription_queue` table，含三個 indexes（`status`、`position`、`show_id`）與 UNIQUE constraint on `episode_id`
- [x] 1.3 To satisfy "Show schedule settings persisted per show": 修改 `backend/app/models/show_schedule.py`：新增 `last_refresh_at` (DateTime nullable)、`last_refresh_status` (Enum `success`/`failed`/`never`, default `never`)、`last_refresh_message` (String 500 nullable)、`max_episodes_per_run` (Integer NOT NULL)；移除舊的 `max_episodes` 欄位
- [x] 1.4 To satisfy "Show schedule settings persisted per show" + "max_episodes_per_run is required": 在 `backend/alembic/versions/` 新增 migration 檔擴充 `show_schedules`：先 add columns（`max_episodes_per_run` 含臨時 server_default=5）、UPDATE 把舊 `max_episodes` 值搬到 `max_episodes_per_run`（`max_episodes=0` 的 row 寫成 5）、drop server_default、drop `max_episodes` column
- [x] 1.5 To satisfy "Global app_settings table for runtime configuration" (per design "Settings 表設計" — Goals: 並行上限可在不重啟 worker 的情況下調整): 在 `backend/app/models/app_settings.py` 新增 model `AppSettings`，欄位 `id` (Integer PK, default 1)、`max_concurrent_transcriptions` (Integer NOT NULL default 1)、`monthly_cost_cap_usd` (Numeric(10,2) nullable)。在 `__init__.py` 註冊；singleton 透過 application-layer enforce（INSERT ... ON CONFLICT id=1 DO UPDATE）依 design 段落 "Settings 表設計"
- [x] 1.6 To satisfy "Global app_settings table for runtime configuration": 在 `backend/alembic/versions/` 新增 migration 檔建立 `app_settings` table 並 INSERT 一筆 default row `(id=1, max_concurrent_transcriptions=1, monthly_cost_cap_usd=NULL)`

## 2. Schema 與 API：queue 操作

- [x] 2.1 To satisfy "Cancel pending row" + "Mark row as ignored": 在 `backend/app/schemas/queue.py` 新增 Pydantic schemas：`QueueRowOut`（rich response）、`QueueListOut`、無 input body schema（cancel/ignore 走 path param）
- [x] 2.2 To satisfy "Cancel pending row": 在 `backend/app/api/queue.py` 新增 router `/admin/queue`，實作 `GET /admin/queue` 回傳所有 row（依 status 分組，pending 依 position asc、其他依 enqueued_at desc）
- [x] 2.3 To satisfy "Cancel pending row": 在 `backend/app/api/queue.py` 實作 `POST /admin/queue/{queue_id}/cancel`：if `status != pending` 回 409；否則 UPDATE status=cancelled、回傳 200
- [x] 2.4 To satisfy "Mark row as ignored": 在 `backend/app/api/queue.py` 實作 `POST /admin/queue/{queue_id}/ignore` 與 `POST /admin/queue/{queue_id}/unignore`，分別 set ignored=true / false（任何 status 都可），回傳 200
- [x] 2.5 To satisfy "Cancel pending row": 在 `backend/app/main.py` 註冊 queue router

## 3. Schema 與 API：app_settings

- [x] 3.1 To satisfy "Global app_settings table for runtime configuration": 在 `backend/app/schemas/settings.py` 新增 `AppSettingsOut`、`AppSettingsUpdate`（Pydantic Field 驗證 `max_concurrent_transcriptions: int = Field(ge=1, le=3)`）
- [x] 3.2 To satisfy "Global app_settings table for runtime configuration": 在 `backend/app/api/settings.py` 新增 `GET /admin/settings` 與 `PUT /admin/settings`，後者用 `INSERT ... ON CONFLICT (id=1) DO UPDATE` 確保 singleton
- [x] 3.3 To satisfy "Global app_settings table for runtime configuration": 在 `backend/app/main.py` 註冊 settings router

## 4. Worker：dispatcher（從 DB pop）

- [x] 4.1 To satisfy "Dispatcher pops jobs from DB queue in FIFO order" (per design "Dispatcher: poll-based, not pubsub" — Goals: queue row 的 status 是唯一 source of truth；Non-Goals: 不做 priority / round-robin 排序): 在 `backend/app/workers/dispatcher.py` 寫 standalone process entry，每秒執行一次 pop 邏輯：先 `SELECT COUNT(*) FROM transcription_queue WHERE status='running'`，若 < `max_concurrent_transcriptions` 則執行 `SELECT ... WHERE status='pending' AND ignored=false ORDER BY position ASC LIMIT 1 FOR UPDATE SKIP LOCKED`，找到後 UPDATE status=running, started_at=now, COMMIT，再 `celery_app.send_task("app.workers.tasks.transcribe_episode", args=[episode_id])`
- [x] 4.2 To satisfy "Dispatcher pops jobs from DB queue in FIFO order": 在 `backend/app/services/settings_cache.py` 新增 `get_max_concurrent()` helper，使用 `cachetools.TTLCache(maxsize=1, ttl=60)` 包裝 DB 讀取
- [x] 4.3 To satisfy "Dispatcher pops jobs from DB queue in FIFO order" (per design "Position assignment uses MAX(position) + 1, not gaps"): 修改 `backend/app/workers/dispatch.py`：保留 `enqueue_transcription(episode_id)` 函式簽名，但實作改為「INSERT/UPDATE row 到 `transcription_queue`」，遵循 spec 的 enqueue 與 re-enqueue 規則（用 `INSERT ... ON CONFLICT (episode_id) DO UPDATE SET status='pending', position=(SELECT COALESCE(MAX(position),0)+1 FROM transcription_queue), started_at=NULL, finished_at=NULL, error_message=NULL`）
- [x] 4.4 To satisfy "Dispatcher pops jobs from DB queue in FIFO order": 在 `Dockerfile` 補充註解：dispatcher 啟動指令 `python -m app.workers.dispatcher`；在 `backend/docker-compose.yml` 新增 `dispatcher` service，command 指向 dispatcher entry，depends_on db + redis

## 5. Worker：transcribe_episode 寫回 queue row

- [x] 5.1 To satisfy "transcribe_episode task writes outcome back to queue row": 修改 `backend/app/workers/tasks.py` 的 `transcribe_episode`，在 task 開頭（取得 show_id 後）UPDATE queue row 的 `started_at = now if started_at is null`
- [x] 5.2 To satisfy "transcribe_episode task writes outcome back to queue row" + "Mid-task cancellation aborts artifact writes": 修改 `transcribe_episode` 在寫 transcript 之前重新 SELECT queue row，若 `status = cancelled` 則記 log 並 return 不寫任何 transcript / chunk / segment 資料
- [x] 5.3 To satisfy "transcribe_episode task writes outcome back to queue row" + "Permanent failure records error message": 修改 `transcribe_episode` 在 successful exit 時 UPDATE queue row `status=completed, finished_at=now, error_message=NULL`；在 PERMANENT_ERRORS 例外的 except block UPDATE `status=failed, finished_at=now, error_message=str(exc)[:2000]`
- [x] 5.4 To satisfy "Concurrency limit respected": 修改 `backend/app/workers/throttle.py` 的 `acquire_global_slot` 改為從 `settings_cache.get_max_concurrent()` 動態取值，移除呼叫端傳入 `max_concurrent` 參數，更新所有 caller

## 6. Cron Tick

- [x] 6.1 To satisfy "Cron tick triggers refresh and enqueue per schedule": 在 `backend/app/workers/cron_tick.py` 新增 Celery task `cron_tick`，內部邏輯：取當前 UTC HH:MM、SELECT show_schedules WHERE enabled=true，對每個 schedule 判斷 `frequency=daily` 且 `run_time == current_HHMM`、或 `frequency=weekly` 且當天為 Monday 且 run_time == current_HHMM
- [x] 6.2 To satisfy "Disabled schedules are skipped" + "Manual frequency disables cron": 上述 SQL 已過濾 enabled=true；在 task 內部 if 判斷裡 explicit skip `frequency=manual` 的 row（即使誤被選入也不處理）
- [x] 6.3 To satisfy "Daily schedule fires at run_time" + "Refresh failure is recorded and enqueue is skipped": 對每個 due 的 show，呼叫既有 episode refresh 邏輯（從 `backend/app/api/episodes.py` 抽出共用 service `refresh_show_episodes(show_id)`，回傳 `(success: bool, new_episode_count: int, error_message: Optional[str])`）；refresh 完成後 UPDATE `show_schedules.last_refresh_at=now`、若 success 則 `last_refresh_status=success, last_refresh_message=f"+{N} 集"`；若 failed 則 `last_refresh_status=failed, last_refresh_message=err[:500]` 並 `continue` 到下個 show
- [x] 6.4 To satisfy "Daily schedule fires at run_time": refresh 成功後 SELECT `max_episodes_per_run` 個未轉錄 episode（episodes WHERE show_id=? AND id NOT IN (SELECT episode_id FROM transcription_queue WHERE status IN ('completed','running','pending')) ORDER BY published_at DESC LIMIT N），對每個呼叫 `enqueue_transcription(episode.id)`
- [x] 6.5 To satisfy "One show's failure does not stop other shows": 把每個 show 的處理包在 `try/except Exception` 內，例外只記 log 不 raise；確保整個 cron_tick 不會因某個 show 例外而中斷
- [x] 6.6 To satisfy "Cron tick triggers refresh and enqueue per schedule" (per design "Use Celery Beat for cron tick scheduling" + "Use a single 1-minute tick instead of per-schedule beat entries"): 修改 `backend/app/workers/celery_app.py` 加入 `beat_schedule` 設定：唯一條目 `cron-tick` 用 `crontab(minute="*")` 觸發 `app.workers.cron_tick.cron_tick`
- [x] 6.7 To satisfy "Cron tick triggers refresh and enqueue per schedule": 在 `backend/docker-compose.yml` 新增 `beat` service，command `celery -A app.workers.celery_app beat --loglevel=info`；在 `Dockerfile` 補充註解：beat 啟動指令

## 7. Show 刪除 cascade cancel

- [x] 7.1 To satisfy "Cancel pending and running rows when show is deleted" (per design "show 刪除時的 queue cleanup 順序"): 修改 `backend/app/api/shows.py` 的 `DELETE /shows/{show_id}` handler：在刪 show 之前先 `UPDATE transcription_queue SET status='cancelled' WHERE show_id=? AND status IN ('pending','running')`、commit、然後再 DELETE show（CASCADE 會清掉 episodes/queue rows）

## 8. Verification（在 Zeabur prod 全部跑過）

- [ ] 8.1 To satisfy "Enqueue an episode for the first time" + "Re-enqueue a previously completed episode": Zeabur prod 上對單集 episode 呼叫 `POST /episodes/{id}/transcribe`，確認 `transcription_queue` 多一筆 row、`position = 上次 max + 1`、status 正常從 pending → running → completed；對該集再呼叫一次，確認**同一個 row** id 被 update 而非新增（檢查 row count）
- [ ] 8.2 To satisfy "Cancel a pending row succeeds" + "Cancel a running row is rejected": 入列 3 集（concurrency=1），對第 2 集呼叫 cancel API 成功（200 + status=cancelled）；對正在 running 的第 1 集呼叫 cancel API 拿到 409
- [ ] 8.3 To satisfy "Ignored failed row is not retried": 手動把某 row 改成 `status=failed, ignored=true`，等 cron tick 跑一輪，確認該 episode 沒被重新 enqueue
- [ ] 8.4 To satisfy "Show deletion cancels pending queue rows first": 為某 show 入列 5 集 pending，呼叫 `DELETE /shows/{show_id}`，確認 API 回 204、查 DB 確認 queue rows 在被 CASCADE 之前 status 都已被改為 cancelled（以 audit log 或 trigger 驗）
- [ ] 8.5 To satisfy "Concurrency change takes effect": Zeabur prod `PUT /admin/settings` 把 `max_concurrent_transcriptions` 從 1 改 3，等 60 秒後入列 5 集，確認同時最多 3 集進入 running
- [ ] 8.6 To satisfy "Daily schedule fires at run_time": 為某 show 設 `enabled=true, frequency=daily, run_time = (current+2 minute UTC), max_episodes_per_run=2`，等 2 分鐘後查 `show_schedules.last_refresh_at` 已更新、`transcription_queue` 多了 ≤ 2 筆 pending row
- [ ] 8.7 To satisfy "Refresh failure is recorded and enqueue is skipped": 暫時把某 show RSS URL 改成 404 URL、設 `enabled=true, frequency=daily, run_time` 即將到，等 cron tick 後確認 `last_refresh_status=failed, last_refresh_message` 含錯誤訊息、queue 沒新增 row
- [ ] 8.8 To satisfy "Successful transcription updates queue row" + "Permanent failure records error message": 觀察 8.1 / 8.6 跑出的 queue row，確認 `started_at` 與 `finished_at` 都被填、`status=completed`；故意觸發 RSS 壞掉的 episode 走 transcribe，確認 `status=failed, error_message` 有內容
- [ ] 8.9 To satisfy "max_episodes_per_run is required": 呼叫 `PUT /shows/{id}/schedule` body 不帶 `max_episodes_per_run` 欄位，確認回 422
