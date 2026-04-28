## 1. 後端：Stale running detection sub-routine

- [x] 1.1 實作「Stale running row detection」requirement +「偵測位置：cron_tick 內加子流程，不開新 Beat 任務」決定：在 backend/app/workers/cron_tick.py 加 helper `_detect_stale_running(Session)`，在 `_run_tick` 開頭（schedule 處理之前）呼叫
- [x] 1.2 實作「Stale 定義：30 分鐘 AND 不在 Celery active∪reserved」與「Inspect 設計：5 秒 timeout + 失敗 skip」決定：用 `celery_app.control.inspect(timeout=5)` 取 active() + reserved()，合併成 `running_ids` set；若兩者皆空 → log warning 後 return（視為 inspect 失敗）
- [x] 1.3 SQL 查詢：選 `transcription_queue` 中 `status=running` 且 `started_at < now - interval '30 minutes'` 的 row（用 SQL 端比較，避免時鐘漂移）
- [x] 1.4 對每筆候選 row 套用雙條件：若 `celery_task_id IS NULL` 或 `celery_task_id NOT IN running_ids` → 標 stale
- [x] 1.5 實作「動作：標 failed、不 re-enqueue」決定：對 stale row 更新 `status=failed`、`finished_at=now`、`error_message='Stale task — worker message lost'`，commit
- [x] 1.6 實作「Slot 釋放：跟 force-cancel 同邏輯」決定：對有 celery_task_id 的 stale row 呼叫 `release_global_slot(celery_task_id)`；celery_task_id=null 跳過 release
- [x] 1.7 整個 `_detect_stale_running` 子流程外層 `try/except Exception`：例外時 log warning 後 return，不影響 cron_tick 後續 schedule 處理

## 2. 測試（pytest 5 情境對應 spec scenarios）

- [x] 2.1 新建 backend/tests/test_cron_tick_stale.py，setup fixture 建 show + episodes + queue rows（不同 status / started_at / celery_task_id 組合）
- [x] 2.2 測試 stale row with celery_task_id not in active list → 標 failed + 呼叫 release_global_slot（mock celery_app.control.inspect + mock release_global_slot 確認被呼叫一次帶 'abc-123'）
- [x] 2.3 測試 stale row with null celery_task_id → 標 failed 但 release_global_slot 不被呼叫
- [x] 2.4 測試 running row with task_id in active list → row 不變、release 不被呼叫
- [x] 2.5 測試 running row started_at < 30 min → row 不變
- [x] 2.6 測試 inspect 兩邊都空 dict → log warning、無 row 被改、cron_tick 主流程仍跑
- [x] 2.7 測試 inspect 拋例外 → log warning、無 row 被改、cron_tick 主流程仍跑

## 3. 部署 + 驗收

- [x] 3.1 push 到 GitHub main 觸發 Zeabur build，等 backend + worker + dispatcher + beat 4 services 部署成功
- [x] 3.2 prod 驗收 — 預埋 stale row：用 service exec 跑 SQL 把某 completed/cancelled row 暫時改回 `status=running, started_at=now()-interval '45 minutes', celery_task_id='fake-stale-001'`（或對某真實 row 直接修改）
- [x] 3.3 等下一次 cron tick（最多 60 秒），確認預埋 row 變 `status=failed` + `error_message='Stale task — worker message lost'` + `finished_at` 已設
- [x] 3.4 prod 驗收 — 真實 long-running 不被誤殺：enqueue 一集較長 podcast，觀察過 30 分鐘前還在 running、celery_task_id 在 inspect active list 內的 row 不被動到（用 service exec 對單筆 row 取樣 + 比對 worker log）
- [x] 3.5 確認 cron_tick log 看得到 detection 結果（log "stale detected: N rows" 或類似），broker 暫斷時看得到 warning skip log
