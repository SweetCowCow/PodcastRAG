## Why

2026-04-28 在 prod 觀察到 worker 改 `--concurrency=3` redeploy 期間，broker 中正在派給舊 worker 的 task 訊息遺失，導致 `transcription_queue` 中 row 永遠停在 `status=running`。dispatcher 因 cap=3 卡滿無法再派新 task → 整個 queue 凍結，需手動用 `POST /admin/queue/{id}/cancel?force=true` 一筆筆清。需要 auto-recovery：cron_tick 每分鐘掃 stale running row 標 failed 釋放 slot，使用者再透過 UI「重試」按鈕決定是否再跑。

## What Changes

- `backend/app/workers/cron_tick.py` 內 `_run_tick` 加新子流程 `_detect_stale_running()`，每 tick（每分鐘）跑一次
- 子流程用 `celery_app.control.inspect(timeout=5).active() | reserved()` 取得當前所有 worker 正在處理 / 預備處理的 task IDs
- 對 `transcription_queue` 中 `status=running` 且 `started_at < now - 30 minutes` 的 row 做雙條件判定：
  - 若 `celery_task_id` 為 null → 直接標 stale
  - 若 `celery_task_id` 不在 inspect 集合內 → 標 stale
  - 若 `celery_task_id` 在集合內 → 跳過（仍在跑）
- 標 stale 的 row 寫回：`status=failed`、`finished_at=now`、`error_message='Stale task — worker message lost'`
- 同步呼叫 `release_global_slot(celery_task_id)` 釋放 Redis throttle slot；celery_task_id=null 時跳過 release
- 若 `inspect()` 拋例外或 timeout → 整個 stale detection 子流程當次 tick 跳過（不影響 schedule refresh + enqueue 主流程），下分鐘再試
- pytest 測試 5 個情境（後續 design / tasks 詳列）

## Non-Goals

- 不做 auto re-enqueue（使用者按 UI「重試」按鈕決定，UI 已存在）
- 不把 30 分鐘閾值做成動態 setting（寫死常數，未來改改 code）
- 不偵測 stuck pending（dispatcher 派任邏輯本身保證 pending 不卡）
- 不偵測 broker queue 訊息積壓（另一個問題，超出本 change scope）
- 不為 inspect 失敗加 retry（broker 暫時不可達 → skip 此 tick，下分鐘自然重試）
- 不改 stale row 的前端 UI（complaint 直接重用 failed row 既有重試 / 忽略按鈕；error_message 即可辨識來源）

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `transcription-queue`: 新增 stale running detection requirement（cron_tick 每分鐘掃 + 雙條件判定 + 標 failed + 釋放 slot）

## Impact

- Affected specs: `transcription-queue`
- Affected code:
  - Modified:
    - backend/app/workers/cron_tick.py
  - New:
    - backend/tests/test_cron_tick_stale.py
- Affected operations: prod cron_tick 每分鐘多跑一個 inspect broadcast（成本可忽略）
