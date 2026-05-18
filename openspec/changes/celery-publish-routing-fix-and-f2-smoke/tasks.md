## 1. Investigate publish-side silent drop

- [ ] 1.1 驗證 H1（broker URL 不一致）：執行 design.md「H1 驗證」SOP，比對 backend / worker / dispatcher / beat 四 service 的 `CELERY_BROKER_URL` 字串；落 `/tmp/broker_url_diff.txt`（**勿印 chat**）。完成標準：拿到四個 service 的 broker URL 一致性結論（completely-identical / differs-on-{field}）。
- [ ] 1.2 驗證 H2（backend broker connection 退化）：在 backend container 執行 `celery_app.broker_connection().ensure_connection()` 與 H2 SOP 的 `.delay()` test call；同時 `redis-cli llen summary` 對照。完成標準：拿到 `(connected, transport_cls, task_id, llen_delta)` 四元組，能判定 publish 是否真的進 broker。
- [ ] 1.3 驗證 H3（task name resolution mismatch）：在 backend container 與 worker container 各列 `celery_app.tasks` 與 `inspect registered`；補驗 `redis-cli llen control` 看 summary task 是否誤路由到 control。完成標準：兩邊 task name string 列表對照表 + control queue 內容快照。
- [ ] 1.4 驗證 H4（summary_task module import 副作用）：在 backend container `import app.workers.summary_task` 後檢查 `task.app` binding；同時對照 worker container 行為。完成標準：拿到 backend 端 task object 的 `(module_loaded, task_obj, task_app_id)` 三元組，能判定 module 是否被正確 bind 到 prod celery_app。
- [ ] 1.5 整理 root cause 報告（落 `docs/case-studies/celery-publish-silent-drop.md` 或對應 case study 檔），含 4 個 hypothesis 各自 evidence + 收斂結論 + 對應修法選擇。完成標準：報告含 reproducible 步驟與證據截圖／log 引用，後續實作者依此就能直接動手。

## 2. Fix publish-side bug

- [ ] 2.1 依 root cause 設計修法（broker config / env 對齊 / task definition 重構 / publish path 加 broker ack 驗證 之一）。完成標準：修法文件化於 case study 報告，PR description 引用 root cause + 修法對應關係。
- [ ] 2.2 實作修法 code 變更：依 root cause 改動對應檔案（候選見 proposal.md Impact section）。完成標準：本機可跑（unit test / import smoke）、`backend/app/workers/celery_app.py` 等動到的檔案 lint 過。
- [ ] 2.3 補單元測試：若 root cause 可以在本機 reproduce（譬如 mock 一個失敗的 broker connection），加 regression test 防止未來再犯。完成標準：新 test 案例獨立 fail-on-revert，跑 `pytest backend/tests/` 全綠不退步。
- [ ] 2.4 publish-side fix 部署：commit + push main → Zeabur backend + worker + dispatcher + beat 四 service redeploy；用 task 1.2 的 SOP test call 再驗一次 publish 真的進 broker。完成標準：test call `r.id` 取得 + `llen summary` 從 0 變 1，或 publish 失敗時 backend 真的 raise。
- [ ] 2.5 chrome-devtools-mcp 跑端到端驗證：開後台→點「重新生成 AI 摘要」→看 worker log 在 10 秒內出現 received。完成標準：截圖 + worker log snippet 留 case study 報告。

## 3. Fix F1 cron_tick leak（beat publish 走 default queue）

- [ ] 3.1 修改 beat schedule 設定（位置：`backend/celerybeat_schedule.py` 或 `celery_app.py` 的 `beat_schedule` dict），每個 entry 顯式加 `options={"queue": "control"}`；包含 cron_tick / quota_digest / db_backup / eval_reminder / tokenizer_reload。完成標準：beat schedule code 含對應 options dict；本機跑 beat 一個 cron cycle log 顯示 task 都送 control queue。
- [ ] 3.2 Prod 驗證：deploy beat → 等一個完整 cron cycle（約 5-10 min）→ `redis-cli llen celery` 持續 0、`redis-cli llen control` 在 cron 觸發瞬間短暫 > 0 後歸零（被 worker 消費）；既有殘留 stuck cron_tick 用 `redis-cli del celery` 清掉一次。完成標準：default `celery` queue 在 24 hr 觀察期內 llen 維持 0。

## 4. F2 主動 smoke（circuit breaker 完整行為驗證）

- [ ] 4.1 觸發 circuit open：用 `SUMMARY_TASK_FORCE_RAISE=true` env flag（或 design 指定的等效手段）讓 summary task entry 強制 raise N 次（N = F2 circuit threshold）；觀察 F2 circuit state 從 closed 轉 open。完成標準：DB / Redis 內 circuit state 欄位顯示 open + 時間戳 + 截圖留證。
- [ ] 4.2 驗證 `paused_task_count` 上升：circuit open 後再送 M 個 summary publish 請求，確認 task 被 pause 不被 worker pick，計數正確。完成標準：`paused_task_count` 數字符合預期 + 截圖。
- [ ] 4.3 驗證 ZSend 告警信送出：circuit open 瞬間應觸發一封告警信到 test recipient；檢查 ZSend log / 收件匣。完成標準：拿到信件 ID + 內文截圖（敏感資訊馬賽克）。
- [ ] 4.4 驗證後台紅 badge：chrome-devtools-mcp 開後台 task 狀態頁，截圖紅色 badge + `paused_task_count` 顯示；對照 4.1 / 4.2 的 DB 數值一致。完成標準：截圖留 case study 報告。
- [ ] 4.5 驗證手動 resume + recovery 信：後台按「resume」按鈕（或 API）→ circuit state 轉 closed → `paused_task_count` 歸零 → ZSend 寄出 recovery 通知信；最後 unset `SUMMARY_TASK_FORCE_RAISE` + redeploy backend / worker。完成標準：resume 動作 + recovery 信 ID + closed state 截圖 + flag 已從 prod env 移除（`zeabur variable list` 驗）。

## 5. 收尾

- [ ] 5.1 Release log 補 entry：依 release log 寫作風格（使用者視角，少技術用語）描述「重新生成 AI 摘要 / 後台告警 / 紅 badge」修好。完成標準：對應 release log MD 檔已 commit、可在前端 release log UI 看到。
- [ ] 5.2 路線圖更新：把 F2 從「待 archive」移到「已 ship」；本 change 列入新近 archive；雙寫 `project_pending_changes.md` memory + `docs/roadmap.md`。完成標準：兩份文件內容一致。
- [ ] 5.3 Archive F2 + 本 change：`spectra archive task-failure-monitoring-and-circuit-breaker` → `spectra archive celery-publish-routing-fix-and-f2-smoke`；確認 specs/ 已合併或維持原狀（依本 change 是否有 spec delta）。完成標準：兩個 change 都在 `openspec/changes/archive/`，`spectra list` 不再顯示為 in-progress。
