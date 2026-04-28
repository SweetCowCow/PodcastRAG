## Why

PodcastRAG 後端的 `ShowSchedule` 表已經存了 `frequency` / `run_time` / `whisper_model` / `max_episodes`，但專案內**完全沒有 cron 元件**——這些欄位是死資料，使用者設了不會自動跑。同時，目前 transcription queue 走 Celery broker FIFO，無法支援拖動排序、優雅 cancel pending、忽略壞集數等 queue 管控操作。

本 change 解決這兩個根本性架構缺口：
1. 把排程從「純配置」變成真正的自動執行
2. 把 queue 從「Celery broker driven」重構成「DB driven」，讓 worker 從 DB 表 pop 任務，使所有 queue 操作都可被原子化記錄與調整

完整需求討論與決策過程見 `docs/case-studies/transcription-queue-discussion.md`。

## What Changes

- 新增 `transcription_queue` 資料表：欄位包含 `id`、`episode_id`、`show_id`、`status`、`position`、`enqueued_at`、`started_at`、`finished_at`、`error_message`、`ignored`、`whisper_model`
- 新增 cron tick worker（透過 Celery Beat），每分鐘掃描 `show_schedules` 表，找出符合 `enabled = true` 且 `frequency` / `run_time` 對到當前時間的 show，依序執行：refresh 集數列表 → 將最新 N 集（`max_episodes_per_run`）入列至 `transcription_queue`
- 新增 dispatcher worker：取代既有的「Celery `send_task` → broker queue」流程；改為從 `transcription_queue` 表依 `position` 順序 pop pending 任務，呼叫既有的 `transcribe_episode` task
- ShowSchedule 新增欄位：`last_refresh_at`（DateTime）、`last_refresh_status`（enum：`success` / `failed` / `never`）、`last_refresh_message`（文字、失敗時填錯誤、成功時填「+N 集」）、`max_episodes_per_run`（Integer、必填、取代既有 `max_episodes` 的 0=unlimited 語意）
- 新增全域 settings 表 `app_settings`：欄位 `max_concurrent_transcriptions`（Integer 1–3，預設 1）、`monthly_cost_cap_usd`（Numeric、預留欄位、本 change 不消費此值）
- Cancel pending：API endpoint 將 `transcription_queue` row 的 `status` 由 `pending` 改 `cancelled`
- Cancel running：明確**不支援**（已啟動 OpenAI API call，cancel 無實質意義）
- 「忽略此集」：API endpoint 將 row 的 `ignored = true`，dispatcher 與 cron tick 永遠跳過 `ignored = true` 的 row（即使其 status 是 failed）
- 刪除 show 時 cascade cancel：show 刪除時，`transcription_queue` 中該 show 的所有 `pending` row SHALL 改為 `cancelled`；`running` row 因為已啟動 API call 無法回收，但 row 會隨 episode CASCADE 被刪除
- `transcribe_episode` task 完成後，必須回寫對應 queue row 的 `status` 與 `finished_at`，讓 UI 可查
- **BREAKING**：既有透過 `dispatch.enqueue_transcription()` 直接 `send_task` 的呼叫點全部改成「插入 queue row」；本 change 不再支援繞過 queue 的轉錄入口

## Non-Goals

- **UI 完全不在本 change 範圍**：「轉錄序列」新頁、「轉錄排程」頁的欄位增補、刪 show 確認視窗、並行上限調整 UI、拖動排序互動等，全部留給後續 change `transcription-queue-and-schedule-ui`
- 不實作 monthly cost cap 的扣款/熔斷邏輯（schema 預留欄位但不消費）
- 不改變 `transcribe_episode` 內部流程（仍走既有 throttle / retry / Whisper 呼叫）
- 不引入 priority queue（採純 FIFO + UI 拖動的設計，UI 部分留給 change 2）
- 不對既有 `task-queue` capability（單集 transcribe task 內部執行模型）做 spec 變動，本 change 只在其前面補一層 dispatcher
- 不調整 Celery worker `--concurrency` 啟動參數；並行控制完全透過 App 層 `max_concurrent_transcriptions` 設定值（既有的 Redis `acquire_global_slot` 機制會讀 settings 表的值）
- 不處理 cron tick 漏跑補發（例如部署期間錯過某個 run_time 不會回補；cron 重啟後等下一個排程點）

## Capabilities

### New Capabilities

- `transcription-queue`: DB-backed FIFO queue 抽象，定義 queue table schema、入列規則、pop 規則、cancel pending、ignore、cascade cancel、並行上限與 dispatcher 行為

### Modified Capabilities

- `transcription-schedule`: 將「純配置」語意升級為「真自動執行」；新增 cron tick 觸發 refresh + 入列、`last_refresh_*` 欄位、`max_episodes_per_run` 必填欄位

## Impact

- Affected specs:
  - 新 `transcription-queue`
  - 改 `transcription-schedule`
- Affected code:
  - New:
    - `backend/app/models/transcription_queue.py`
    - `backend/app/models/app_settings.py`
    - `backend/app/schemas/queue.py`
    - `backend/app/api/queue.py`
    - `backend/app/api/settings.py`
    - `backend/app/workers/cron_tick.py`
    - `backend/app/workers/dispatcher.py`
    - `backend/alembic/versions/<new>_add_transcription_queue.py`
    - `backend/alembic/versions/<new>_extend_show_schedule.py`
    - `backend/alembic/versions/<new>_add_app_settings.py`
  - Modified:
    - `backend/app/workers/celery_app.py`（加入 beat_schedule 設定）
    - `backend/app/workers/dispatch.py`（既有 `enqueue_transcription` 改成插 queue row）
    - `backend/app/workers/tasks.py`（`transcribe_episode` 完成時回寫 queue row）
    - `backend/app/workers/throttle.py`（`max_concurrent` 改從 settings 表讀，不再只用環境變數）
    - `backend/app/models/show_schedule.py`（新增 4 個欄位 + 移除 `max_episodes` 換成 `max_episodes_per_run`）
    - `backend/app/schemas/schedule.py`（同上）
    - `backend/app/api/schedules.py`（接受新欄位）
    - `backend/app/api/shows.py`（刪除 show 時觸發 cascade cancel queue rows）
    - `backend/app/main.py`（註冊新 router）
    - `Dockerfile`（補 Celery Beat 啟動指令說明）
    - `backend/docker-compose.yml`（新增 beat service）
  - Removed: 無
