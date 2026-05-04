## Why

`deploy-resilience`（已 archive）只覆蓋轉錄 task 的 stale-running 自動回收，沒延伸到摘要 task。2026-05-03 batch backfill 190 集摘要時，3 集卡在 `ai_summary_status='running'` 一整天沒人救（worker 重啟、Celery task 消失、狀態沒被更新），需要人工觸發 `regenerate-summary`。本 change 把同樣的 resilience pattern 套用到摘要，並補上 Celery `on_failure` 的明確失敗標記，避免之後再發生靜默卡住。

## What Changes

- **(A) cron_tick 擴充**：beat 每分鐘的 `cron_tick` task 新增 stale-summary 掃描——找 `episodes` 表中 `ai_summary_status='running'` 且 `ai_summary_started_at` 早於 `now() - SUMMARY_STALE_THRESHOLD`（預設 10 分鐘）的列，把狀態重置為 `pending` 並重新 enqueue Celery `generate_episode_summary` task；寫 audit log。
- **(B) Celery `on_failure` handler**：`generate_episode_summary` task 加 `on_failure` callback，task 失敗時自動把 `ai_summary_status` 寫成 `failed` 並把例外訊息存入 `ai_summary_error`（新欄位，nullable text）。
- **(C) 冪等保護**：spec 既有的「status==`done` → 早返、status==`running` → 早返」入口檢查維持不變。cron_tick 在重 enqueue 前先把 status 從 `running` 重置為 `pending`，確保新觸發的 task 不會被既有的 running-skip 擋掉。
- **(C2) 起跑時間欄位**：新增 `episodes.ai_summary_started_at`（TIMESTAMP WITH TIME ZONE, nullable）。task 入口把 status 由 pending 改為 running 時同步寫入；cron_tick 用此欄位判斷是否 stale（`generated_at` 只在 done/failed 時寫，無法代表「正在跑了多久」）。
- **(D) Admin UI 微調**：`AdminPage` Queue Tab 的 `SummaryBadge` 已能顯示 `failed` 狀態 + 重跑按鈕，這次只需在 hover tooltip 加上 `ai_summary_error` 訊息（若有）。
- **(E) Settings**：`backend/app/core/config.py` 新增 `summary_stale_threshold_seconds` setting（預設 600），可透過 env `SUMMARY_STALE_THRESHOLD_SECONDS` 覆寫。
- **(F) Migration**：alembic 加一個 revision 新增 `episodes.ai_summary_error`（nullable text）+ `ai_summary_started_at`（nullable timestamptz）兩個欄位。對既有 `running` 狀態的列，migration 把 `started_at` 設成 `now()`（避免立刻被視為 stale 而誤觸；下個 cron_tick 視真正 stale 才會重置）。

## Non-Goals

- 不改 transcription queue 的 stale detection 邏輯（已在 deploy-resilience 處理）。
- 不重構 cron_tick 的整體結構，只新增一個 helper function。
- 不調整 `episode-ai-summary` 的 chunking / model 選擇邏輯。
- 不加 metrics dashboard 或 alerting（現有 admin queue tab 顯示 `failed` 狀態已足夠）。
- 不調整 backfill API（`/admin/episodes/backfill-summary`）的行為，cron_tick 自動恢復後使用者下次回來看 admin 即可確認結果。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `episode-ai-summary`: 新增 `ai_summary_error` 欄位、Celery `on_failure` 自動標記 failed、task 入口冪等檢查（status=='done' 時 return）。
- `task-queue`: `cron_tick` 任務新增「stale summary 掃描 + 重 enqueue」邏輯。

## Impact

- Affected specs: `episode-ai-summary`、`task-queue`
- Affected code:
  - New:
    - `backend/alembic/versions/<新 revision>_add_ai_summary_error.py`
  - Modified:
    - `backend/app/models/episode.py`（加欄位）
    - `backend/app/workers/summary_task.py`（on_failure handler、入口寫 started_at）
    - `backend/app/workers/cron_tick.py`（新增 `_detect_stale_summary_running` helper，於 `_run_tick` 中呼叫）
    - `backend/app/core/config.py`（新 setting）
    - `backend/app/api/admin.py`（queue 回應加 ai_summary_error 欄位）
    - `src/AdminPage.jsx`（SummaryBadge tooltip 顯示 error）
    - `backend/tests/test_cron_tick.py`（stale summary 測試，若不存在則新增）
    - `backend/tests/test_summary_pipeline.py` 或 `backend/tests/test_summary_integration.py`（on_failure、started_at 寫入測試）
  - Removed: (none)
- 部署影響：4 個 service（backend / worker / dispatcher / beat）皆需 redeploy（migration + 新邏輯）。dispatcher 不需要碰但走同 image。
- 成本：無新 LLM 呼叫；cron_tick 多一次 SELECT 查詢（每分鐘一次，可忽略）。
