## Context

`db-driven-queue-and-real-cron`（archive 於 2026-04-28）導入 DB-backed `transcription_queue` + dispatcher + Celery Beat cron tick；其中 `app_settings.max_concurrent_transcriptions` 控制 dispatcher promote pending → running 的 cap。但部署層 worker service 至今仍是 1 replica `--concurrency=1`，所以 setting 即使設 3，多出來的 running row 只會卡在 Celery broker queue（`task_acks_late=True` + `worker_prefetch_multiplier=1`）等同一個 worker 序列拿任務，沒有真平行。

當前 prod 還殘留 1 筆 stuck running row（episode `831a8c8b-bb09-441a-9500-203910c92b78`），dispatcher 派出但 worker 從沒 ack 處理（Celery 訊息遺失或 pre-deploy worker 吞掉），DB 狀態永遠卡 running。現有 `POST /admin/queue/{id}/cancel` 對 running 一律回 409，無法清。

## Goals / Non-Goals

**Goals**
- 讓 setting=3 真的能同時跑 3 集（dispatcher + Celery broker + 多 replica 自然湧現）
- 提供強制取消 running row 的能力，能中止實際在跑的 Whisper API 呼叫並釋放 DB row + global slot
- 用新 force-cancel 清掉 prod 那筆 stuck running row（驗收動作）

**Non-Goals**
- 不引入 `WORKER_REPLICA_COUNT` env var；replicas 數寫死 3，setting 上限也寫死 3
- 不動 dispatcher 派任邏輯（仍只看 DB cap，不感知實體 replicas）
- 不做 graceful drain on deploy；replicas 重啟期間 in-flight 任務若被 SIGKILL，靠 dispatcher 的 stale-running 偵測恢復（沿用現行機制）
- 不重 Whisper provider 抽象 / fallback

## Decisions

### Worker 平行模型：固定 3 replica × concurrency=1

選擇：Zeabur worker service 寫死 3 replicas，每個 `--concurrency=1`。

**為什麼不用單 replica `--concurrency=3`**：Linode `g6-standard-2`（2 vCPU / 4GB RAM）若 prefork 出 3 個 worker process，每個都載 ffmpeg + 同時做音訊下載 + Whisper API I/O，記憶體與 file descriptor 風險高。Replica 隔離記憶體、進程崩潰只影響自己。

**為什麼不用 dynamic auto-scale**：Whisper 任務時間長（分鐘級），縮放反應慢；replicas 數對使用者體驗來說只是「最多幾條同時跑」，固定上限直白。

### `celery_task_id` 欄位 + worker 寫回時機

queue 表新增 `celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)`。Worker `transcribe_episode` 任務的第一個動作（在 acquire global slot 之前、status 變 running 之前）就 `UPDATE transcription_queue SET celery_task_id=:tid WHERE id=:row_id`，commit 後再進入後續流程。

**為什麼任務開頭就寫**：force-cancel 要 `revoke(task_id)` 必須拿得到 task_id；若等任務做完才寫就沒用。寫早一點不影響任何邏輯。

**為什麼不用 Celery 的 task_id = row id**：Celery task_id 由 broker 端決定（`apply_async()` 回傳的 AsyncResult.id），改寫它需 hack；直接存自然 task_id 更直白。

### Force-cancel 語意：revoke(terminate=True, signal='SIGTERM')

`POST /admin/queue/{id}/cancel?force=true` 對 running row：
1. 從 DB 讀 `celery_task_id`（若為 null 表示 worker 還沒寫回 — 視為「尚未真的開始」，直接標 cancelled，不送 revoke）
2. 呼叫 `celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')`
3. DB row：status `cancelled`、`finished_at = now()`、`error_message = 'Force cancelled by admin'`
4. 釋放 global throttle slot（呼叫 `release_global_slot(task_id)`）
5. 回 200，body 帶 `{"force_cancelled": true, "celery_task_id": "..."}`

**SIGTERM 而非 SIGKILL**：給 worker 5 秒做 cleanup（關閉 audio file、寫 partial log）；若 task 沒在 hard 時限內死掉，Celery 會升級為 SIGKILL（用預設 `worker_max_tasks_per_child` 行為）。

**SIGTERM 對 in-flight Whisper API 呼叫的影響**：httpx request 在 signal 中斷下會 raise，整個 task function 會 raise → Celery 視為 failure → 但因為 row 已被 admin 標 cancelled，task 寫回的失敗 status 應該被忽略。`tasks.py` 在 finally 區塊 update DB status 時 SHALL 檢查 row 當前 status：若已是 `cancelled` 則不覆蓋。

### 普通 cancel 對 running 維持 409

不帶 `force` 的 cancel 對 running row 仍回 409，UI 普通「取消」按鈕只顯示在 pending row。force-cancel 是獨立的紅色按鈕含 confirm dialog。**為什麼不合併**：避免使用者誤點普通 cancel 殺到正在跑的任務；force 是有意識的破壞性動作。

### Setting 上限寫死 3（前後端）

- 後端 `PUT /admin/settings.max_concurrent_transcriptions` 接受 1–3 整數，超過回 422
- 前端 `<input type="number" max="3">` 並顯示 helper text「上限 3，受 worker replicas 限制」
- 不引入 env var；未來若改 replicas 需同步改前後端常數

## Risks / Trade-offs

- **3 replicas 同時送 Whisper API → 觸發 OpenAI rate limit**：現有 api-health-tracker + 6 分類錯誤已能觀察 quota_exceeded；這個 change 不額外加 rate-limit 退避，靠 setting 動態降為 1–2 即可緩解 → Mitigation: 文件記錄「遇到 429 大量集中時把 setting 調 1」。
- **revoke 訊息遺失（broker 抖動或 worker 沒收到）**：DB row 仍會被標 cancelled，但 Celery task 還在跑 → 浪費資源直到自然完成；finally 區塊的 status 檢查確保不會反覆 cancelled ↔ failed → Mitigation: 記錄事件，不阻塞使用者。
- **worker 寫 celery_task_id 與 dispatcher promote 的競態**：dispatcher 把 row promote 到 running 後 send task；worker 一啟動就 update celery_task_id。若 force-cancel 在這中間到（row=running 但 celery_task_id=null），按決議走「無 task_id 路徑」直接標 cancelled → worker 啟動時偵測 row.status≠running 應主動退出 → Mitigation: `tasks.py` 任務開頭加 status 檢查，cancelled 直接 return。
- **多 replica 並行 throttle slot 競爭**：現行 `acquire_global_slot` 用 Redis SETNX with TTL 已是 atomic，多 replica 安全；但 slot key 是 task_id，每個任務一把 → 確認 dispatcher 的 cap 仍是真實上限（Redis slot 主要用於 stale running 偵測，不取代 cap）。

## Migration Plan

1. 部署 backend（含新欄位 + alembic migration + force-cancel API + worker 寫回）
2. 部署 worker（新版 task 程式碼）— 此時 replicas 仍 1
3. 部署 frontend（UI 改動）
4. 在 Zeabur dashboard / CLI 把 worker service replicas 從 1 改 3，等待新 replicas ready
5. 驗收：同時 enqueue 5 集，觀察 3 個 running 同時跑
6. 用 force-cancel 清 prod stuck row（episode `831a8c8b-...`）

**Rollback**: 把 worker replicas 改回 1；新 API force 參數即使被誤呼叫，不帶 force 行為不變，已部署的程式碼可保留。celery_task_id 欄位 nullable，不影響舊程式碼。

## Open Questions

- prod stuck row 的 `celery_task_id` 為 null（舊版部署時還沒這欄位），force-cancel 會走「無 task_id 路徑」直接標 cancelled，不需 revoke — 已在 Decisions 涵蓋，無未決事項。
