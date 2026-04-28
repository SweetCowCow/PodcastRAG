## 1. DB schema 變更（DB-backed transcription queue table）

- [x] 1.1 修改 DB-backed transcription queue table：在 backend/app/models/transcription_queue.py 新增 `celery_task_id: Mapped[str | None]` 欄位，String(64), nullable=True，無 server_default
- [x] 1.2 建 alembic migration `backend/alembic/versions/<rev>_add_celery_task_id_to_queue.py`，upgrade 加欄位、downgrade 移除
- [x] 1.3 本地 `alembic upgrade head` 驗證 migration 跑得過，confirm 欄位存在

## 2. Worker 寫回 celery_task_id + 處理 cancelled（celery_task_id 欄位 + worker 寫回時機，transcribe_episode task writes outcome back to queue row）

- [x] 2.1 實作「`celery_task_id` 欄位 + worker 寫回時機」決定：在 backend/app/workers/tasks.py 的 transcribe_episode task writes outcome back to queue row 路徑入口（acquire_global_slot 之前）新增 `UPDATE transcription_queue SET celery_task_id=:tid WHERE episode_id=:eid` + commit，使用 `self.request.id`
- [x] 2.2 寫完 celery_task_id 後，re-read 該 row 的 status；若 `status='cancelled'`（force-cancel arrives before worker starts 場景）直接 return 不做任何後續處理（不 acquire slot、不下載音訊、不寫 transcript）
- [x] 2.3 修改 task 的 finally / except 區塊：寫回 status 前 re-read row 當前 status，若已是 `cancelled` 則不覆蓋為 failed，僅 log 並退出（mid-task force-cancel preserves cancelled status 場景）
- [x] 2.4 補單元測試或 mock 測試：(a) task 入口正確寫 celery_task_id；(b) cancelled-before-start 提早 return；(c) cancelled-mid-task 不覆寫 status
- [x] 2.5 重新 enqueue 已完成 episode 時清空 celery_task_id（檢查 dispatch.py / dispatcher.py 的 re-enqueue 路徑，確保 status=pending 時同步 set celery_task_id=null）

## 3. Force-cancel API（Force-cancel 語意：revoke + 普通 cancel 對 running 維持 409，Cancel pending row）

- [x] 3.1 擴充 Cancel pending row endpoint：在 backend/app/api/admin.py（或實際的 cancel endpoint 檔案）對 `POST /admin/queue/{id}/cancel` 新增 `force: bool = Query(False)` 參數，依「Force-cancel 語意：revoke(terminate=True, signal='SIGTERM')」決定實作
- [x] 3.2 實作「普通 cancel 對 running 維持 409」：不帶 force 時 pending → cancelled HTTP 200；非 pending（含 running）→ HTTP 409
- [x] 3.3 帶 force=true、status=running 時：(a) 讀 celery_task_id；(b) 若非 null，呼叫 `celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')` 並呼叫 `release_global_slot(task_id)`；(c) UPDATE row 為 status=cancelled, finished_at=now, error_message='Force cancelled by admin'；(d) 回傳 `{"force_cancelled": true, "celery_task_id": <id or null>}`
- [x] 3.4 帶 force=true、status=running 但 celery_task_id=null：跳過 revoke 與 release_slot，只更新 DB row
- [x] 3.5 帶 force=true 但 status 為 completed/failed/cancelled：仍回 HTTP 409（terminal states 不可動）
- [x] 3.6 補 pytest 測試：4 種情境（no-force pending OK、no-force running 409、force running with task_id revoke + DB update、force running null task_id only DB update、force completed 409）

## 4. 前端 UI（已移出本 change scope）

實作中發現 AdminPage.jsx 沒有「轉錄序列」rows 列表 tab，且 max_concurrent_transcriptions 也沒有 setting input UI — 這些屬於前次 archived change `db-driven-queue-and-real-cron` 預留給 `transcription-queue-and-schedule-ui` 的範疇。本 change 改為只交付後端 + 部署，UI 留給下一個 change（要記得把 force-cancel 按鈕、普通 cancel 按鈕、max=3 input 一起做）。

## 5. 部署 + 驗收（Worker service runs with concurrency 3 in production，Worker 平行模型）

- [x] 5.1 push 上述變更到 GitHub main 觸發 Zeabur build；等 backend、worker、frontend 三個 services 部署成功
- [x] 5.2 落實「Worker 平行模型」與「Worker service runs with concurrency 3 in production」：把 worker service（ID `69eb1c620da29f05f49a4e2a`）`START_COMMAND` env var 改為 `celery -A app.workers.celery_app worker --loglevel=info --concurrency=3`，redeploy 等 ready
- [x] 5.3 prod 驗收 — 平行：把 setting 設為 3，從 admin UI 同時 enqueue 5 集，觀察 dispatcher log 與 DB `started_at` 確認 3 個 row 同時 running（時間差 < 10 秒）
- [x] 5.4 prod 驗收 — force-cancel running with celery_task_id：對其中一個 running row 按「強制取消」，確認 DB status=cancelled、worker log 顯示 SIGTERM 中止、其他 running 不受影響、Redis throttle slot 釋放
- [x] 5.5 prod 驗收 — force-cancel stuck row（celery_task_id=null）：對 episode `831a8c8b-bb09-441a-9500-203910c92b78` 的 stuck running row 按「強制取消」，確認 DB row 標 cancelled 且回應 body 的 celery_task_id 為 null
- [x] 5.6 prod 驗收 — 普通 cancel 對 running 仍 409：對另一個 running row 用 `POST /admin/queue/{id}/cancel`（不帶 force），confirm 收到 HTTP 409
- [x] 5.7 ~~用 chrome-devtools-mcp 跑一遍 admin UI~~（移出 scope — UI 已延後到下個 change）
