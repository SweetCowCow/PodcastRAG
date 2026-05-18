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
- [ ] 2.4 deploy + prod 重驗：commit + push（**user 接手** push）→ Zeabur 4 service redeploy → 用 task 1.2 SOP 再驗 publish。**user + Claude 接手**。
- [ ] 2.5 chrome-devtools-mcp 端到端：開後台→「重新生成 AI 摘要」→10 秒內 worker log 出 received。**user + Claude 接手**。

## 3. Fix F1 cron_tick leak（beat publish 走 default queue）

- [x] 3.1 `backend/app/workers/celery_app.py` `beat_schedule` 全部 9 個 entry（cron-tick / quota-digest / appeal-digest / eval-reminder / db-backup / usage-collector / usage-alert / failure-alert / circuit-probe）顯式加 `options={"queue": "control"}`。+ 新增 regression test `test_beat_schedule_all_entries_route_to_control_queue`（`tests/test_celery_routing.py`），現 20 passed（原 19）。
- [ ] 3.2 prod 驗證：deploy beat → 等一個 cron cycle → llen celery 持續 0；既有殘留 stuck cron_tick `redis-cli del celery` 手動清一次。**user 接手**。

## 4. F2 主動 smoke（circuit breaker 完整行為驗證）

> **user + Claude 接手**（agent 不跑此段；需要 chrome-devtools-mcp + 後台 UI 操作 + ZSend 觀察）

- [ ] 4.1 觸發 circuit open：用 `SUMMARY_TASK_FORCE_RAISE=true` env flag 讓 summary task entry 強制 raise N 次（N = F2 circuit threshold）。**user + Claude 接手**。
- [ ] 4.2 驗證 `paused_task_count` 上升。**user + Claude 接手**。
- [ ] 4.3 驗證 ZSend 告警信送出。**user + Claude 接手**。
- [ ] 4.4 驗證後台紅 badge（chrome-devtools-mcp）。**user + Claude 接手**。
- [ ] 4.5 驗證手動 resume + recovery 信 + unset flag。**user + Claude 接手**。

## 5. 收尾

> **user + Claude 接手**

- [ ] 5.1 Release log 補 entry。**user + Claude 接手**。
- [ ] 5.2 路線圖更新（雙寫 memory + docs/roadmap.md）。**user + Claude 接手**。
- [ ] 5.3 Archive F2 + 本 change。**user + Claude 接手**。
