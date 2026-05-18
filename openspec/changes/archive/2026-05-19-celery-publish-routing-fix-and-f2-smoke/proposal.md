## Why

F2（`task-failure-monitoring-and-circuit-breaker`，2026-05-18 ship）的部署看起來綠了，但收尾 smoke 抓到 publish-side silent drop，等於 F2 本身的主動驗證流程被卡住、無法宣告完整 ship。

**Reproducible 證據鏈（2026-05-18 12:39 UTC）**：

1. Chrome POST `https://api.podcastrag.app/admin/episodes/{id}/regenerate-summary` × 3 次
2. Backend log（已驗）：三筆都回 `200 OK`，無 traceback
3. Backend response body：`{"enqueued": true}`
4. Worker log（已驗）：12:25 startup ~ 12:40+ 完全沒看到 `Task app.workers.summary_task.generate_episode_summary[...] received`
5. Redis `summary` queue `llen=0`（debug agent 進 worker container 確認）
6. F2 `paused_task_count` 維持 0、circuit `closed` 沒開
7. `cron_tick` / `transcribe_episode` / `topic_task` 全部正常 pick → routing+worker 沒整體壞，**只 summary publish silent drop**

**附帶發現**：default `celery` queue 殘留 1 筆 stuck `cron_tick` → beat publish 也走錯 routing（F1 殘留 leak，未被 F1 完全清掉）。

**前置事實（必要 context）**：

- 部署狀態已驗 OK：backend / worker / dispatcher / beat 四個 service 全跑 commit `0802a758`，含完整 F2 code → root cause **不是 stale 部署**，而是 code-side。
- code 表面對：
  - `backend/app/api/admin/summary_ops.py` line 42-45 lazy import + `.delay(str(episode_id))` 是標準 Celery 用法
  - `backend/app/workers/celery_app.py` `_TASK_ROUTES` 含 `"app.workers.summary_task.generate_episode_summary": {"queue": "summary"}`
  - `backend/app/workers/summary_task.py` line 119-121 `@celery_app.task(base=SummaryTask, name="app.workers.summary_task.generate_episode_summary", ...)` task name explicit
  - `celery_app.py` `include=[..., "app.workers.summary_task", ...]` 有 include
  - Worker startup banner 確認 `summary` queue subscribed
- 但 publish 還是 silent drop → root cause 須調查。

## What Changes

- **Investigate root cause**：比較 backend FastAPI process 與 Celery worker process 的 broker 設定 / import 路徑 / task module 副作用，定位 publish-side silent drop。
- **Fix publish-side bug**：依 investigation 結果修改 code 或 config，使 `.delay()` 真的把 task 推進 broker。
- **Fix F1 cron_tick leak**：beat schedule entry 顯式指定 `options.queue="control"`（或對等 fix），讓 cron_tick 不再被 publish 到 default `celery` queue。
- **跑完整 F2 主動 smoke**：circuit threshold 達標 open / `paused_task_count` 上升 / ZSend 告警信送出 / 手動 resume / circuit recovery / 後台紅色 badge 顯示。
- **可選串接**：F2 fallback typed exception wiring（合 `aihub-adapter` follow-up；若 root cause 與 fallback path 共用 code 路徑就一次解，否則拆 follow-up change）。

## Non-Goals (optional)

- **不**改 F2 spec（`task-failure-monitoring-and-circuit-breaker`）的 requirement 文字。
- **不**動 circuit breaker threshold / TTL / pause window 等業務參數。
- **不**換 broker（Redis 留著，不改 RabbitMQ / SQS）。
- **不**重構 Celery app init 結構（除非 investigation 證實這就是 root cause）。
- **不**動 worker concurrency / queue 拆法（F1 既有 4 queue 不變）。

## Capabilities

### New Capabilities

（無 — 本 change 是 bug fix + 驗證收尾，不引入新 capability）

### Modified Capabilities

<!-- Investigation 完成前無法確定是否改動 spec requirement。
     若 root cause 是純 config / env / deploy 層面（broker URL 不一致）→ 不改 spec，純行為 fix。
     若 root cause 牽動 task-queue spec 對「publish path 必須在 send_task 後驗證 broker ack」的要求 → 補 task-queue spec delta。
     Investigation 階段（tasks 1.x）會決定，必要時於 apply 階段以 ingest 流程補 spec 檔。 -->

（待 investigation 確認後補）

## Impact

- Affected specs：可能影響 `task-queue`（publish path 行為）；待 investigation 確認。
- Affected code（候選清單，視 root cause 收斂）：
  - `backend/app/workers/celery_app.py`（broker config / init / 結果後端設定）
  - `backend/app/api/admin/summary_ops.py`（publish 呼叫點，可能加 broker ack 驗證）
  - `backend/app/workers/summary_task.py`（task 定義副作用 / F2 base class）
  - `backend/app/workers/cron_tick.py` 或 `backend/celerybeat_schedule.py` 對等檔（cron_tick leak fix）
  - 可能 `entrypoint.sh` / Zeabur env（CELERY_BROKER_URL 對齊）
- Deploy：可能影響 backend + worker + dispatcher + beat 四 service env / redeploy。
- 對使用者：修好之後「重新生成 AI 摘要」按鈕真的會跑；後台 task 狀態頁的紅色 badge 在 circuit open 時真的會亮。
