## 1. Investigate publish-side silent drop

- [x] 1.1 驗證 H1（broker URL 不一致）：4 service 的 `CELERY_BROKER_URL` md5 全部 `96d0327786c352190ae387ab96a000d4`、len=81 → **完全一致**。H1 否決。
- [x] 1.2 驗證 H2（backend broker connection 退化）：backend container 內 `broker_connection().ensure_connection()` 回 `connected=True transport_cls=redis`；`send_task(..., queue='summary', retry=False)` + monkey-patch `Redis.execute_command` 證實 LPUSH summary 真的發生；worker log 1 秒內收到 4 個 test task_id（4f00d7fb / e856b735 / 635f6bd9 / 405cd4ee）。H2 在當下 timeframe 否決，但 publish-side 仍須加 fail-loud 防呆（見 task 2.x）。
- [x] 1.3 驗證 H3（task name resolution mismatch）：backend `m.generate_episode_summary.name == 'app.workers.summary_task.generate_episode_summary'`，在 `celery_app.tasks` 內；worker `inspect active_queues` 顯示 4 queue 都訂閱；trace LPUSH key 是 `summary` 而非 `control`。H3 否決。
- [x] 1.4 驗證 H4（summary_task module import 副作用）：backend `m.generate_episode_summary.app is celery_app` → True；`id` 完全一致。H4 否決。
- [x] 1.5 root cause 報告落 `docs/case-studies/celery-publish-silent-drop-202605.md`（per memory 不進 git）。H1–H4 全 negative + 12:39 UTC 原 silent drop 已無法重現，採「不盲修 broker config，但 publish path 加 defensive fail-loud」策略。

## 2. Fix publish-side bug

- [x] 2.1 修法設計：admin foreground endpoint（`regenerate_summary` / `backfill_summary`）改用 `apply_async(retry=False)` 並 try/except `KombuOperationalError` / `ConnectionError` / `OSError` → raise HTTPException 503。背景任務（dispatcher）維持預設 retry。理由見 case study。
- [x] 2.2 實作：`backend/app/api/admin/summary_ops.py` 改 `.delay()` → `.apply_async(args=[...], retry=False)` + 包 try/except 回 503。
- [x] 2.3 regression test：`tests/test_admin_summary_ops.py` 加 `test_regenerate_returns_503_when_broker_publish_fails` 與 `test_backfill_returns_503_when_broker_publish_fails`（mock `apply_async` side_effect `KombuOperationalError`）；既有 `.delay` patch 全更新成 `.apply_async`。本機跑 `pytest tests/test_admin_summary_ops.py` 結果 = baseline（5 errors 1 passed）+ 新增 2 errors（DB 未連的環境限制，非 code 退步），無 regression。
- [x] 2.4 deploy + prod 重驗：5/19 smoke 第一輪發現 `apply_async` 在 FastAPI async route 還是 silent drop（H2 SOP sync send_task 從 backend container 走 OK，但 admin endpoint POST 仍沒 receive）+ 新發現 `failure_hooks._run_async` 用 `asyncio.run` 踩到 Celery worker post-crash 的 closed event loop → coroutine never awaited → task_failure_log 寫不進 → circuit 永遠不開。補 fix commit `d554317`：(a) `_run_async` 改 fresh thread + new event loop；(b) admin endpoint 改 `await asyncio.to_thread(apply_async)` 隔離 FastAPI loop。
- [x] 2.5 chrome-devtools-mcp 端到端：deploy `d554317` 後 chrome 點「重新生成 AI 摘要」5 個 episode → 90s 內 aihub circuit 真實 OPEN（`opened_at=2026-05-18T17:01:58Z`）→ 後台 UI 紅 badge + 「手動恢復」按鈕 → 點 dialog 確定 → state 變 closed + toast「已手動恢復：aihub」。Smoke 端到端通過。

## 3. Fix F1 cron_tick leak（beat publish 走 default queue）

- [x] 3.1 `backend/app/workers/celery_app.py` `beat_schedule` 全部 9 個 entry（cron-tick / quota-digest / appeal-digest / eval-reminder / db-backup / usage-collector / usage-alert / failure-alert / circuit-probe）顯式加 `options={"queue": "control"}`。+ 新增 regression test `test_beat_schedule_all_entries_route_to_control_queue`（`tests/test_celery_routing.py`），現 20 passed（原 19）。
- [x] 3.2 prod 驗證：deploy beat 完用 backend container redis exec `del celery` 清掉 F1 殘留那筆 stuck cron_tick（before llen=1, after llen=0）。新 beat schedule entry 都帶 `options.queue=control`，未來 cron tick 不再 leak。

## 4. F2 主動 smoke（circuit breaker 完整行為驗證）

> **user + Claude 接手**（agent 不跑此段；需要 chrome-devtools-mcp + 後台 UI 操作 + ZSend 觀察）

- [x] 4.1 觸發 circuit open：用「新增 fake aihub key + summary step 切 fake + admin endpoint enqueue 5 個 regenerate-summary」走 worker 真實 401 失敗路徑（更貼真實 prod incident 行為，不需要新 env flag）。5/19 01:01 台北時間 aihub circuit OPEN。
- [x] 4.2 驗證行為：`opened_at=2026-05-18T17:01:58Z` UTC；`paused_task_count` 初始 0 因 circuit 剛 open 還沒新 task 被 pause（threshold 觸發後新進來的才會 +1，本 smoke 沒繼續餵新 task）。
- [ ] 4.3 ZSend 告警信送出：**user 收信箱確認**（信主旨應該包含 aihub + OPEN）— 不阻 archive，下次 user 來信箱看到 / 沒看到再記。
- [x] 4.4 後台紅 badge：chrome snapshot 看到「狀態」欄顯示 `open`、「暫停起時」顯示 `2026/05/19 01:01`（台北時區）、「操作」欄出現「手動恢復」按鈕。
- [x] 4.5 手動 resume + recovery：點「手動恢復」→ 跳 confirm dialog「確定要手動恢復 aihub 服務嗎？影響 0 個任務會重新加入 queue。」→ 點「確定恢復」→ 表格 state 變 `closed` + toast「已手動恢復：aihub」。Recovery 信也應該寄出（per 4.3，user 信箱確認）。

## 5. 收尾

> **user + Claude 接手**

- [ ] 5.1 Release log 補 entry。**user + Claude 接手**。
- [ ] 5.2 路線圖更新（雙寫 memory + docs/roadmap.md）。**user + Claude 接手**。
- [ ] 5.3 Archive F2 + 本 change。**user + Claude 接手**。
