## 1. Worker：permanent-fail 收尾修復（D1）

- [x] 1.1 實作 spec「Permanent errors short-circuit Celery retry」修訂：修 backend/app/workers/tasks.py `_run` 的 PERMANENT_ERRORS except 區塊：(a) 狀態收尾（transcript 標 failed + `_mark_queue_finished(failed)`）移到 `record_task_failure` 之前；(b) `record_task_failure` 包 try/except，例外只 log 不外拋；(c) `retry_count` 改傳 0、移除 `self` 引用。驗收 = 該區塊不再引用 `self`（grep 確認）＋新測試通過
- [x] 1.2 新增 backend/tests/test_permanent_fail_terminal.py：mock `record_task_failure` 直接 raise，斷言 permanent 錯誤後 transcript.status='failed'、queue row status='failed'、函式正常返回不拋 NameError；另一案例斷言 `retry_count=0` 有寫入 task_failure_log（record 正常時）。跑 backend 既有 ASR 相關測試零新增失敗

## 2. Worker：連續失敗終止狀態（D2）

- [x] 2.1 alembic revision：transcription_queue 加 `failure_count INTEGER NOT NULL DEFAULT 0`（additive，含 server_default）；本機 upgrade/downgrade 各跑一次驗證
- [x] 2.2 實作 spec「Consecutive lost-run counter terminates the revive loop」：backend/app/workers/lifecycle.py orphan-revert：revert running→pending 時 `failure_count += 1`；達 `MAX_CONSECUTIVE_FAILURES=3` 改標 failed + error_message「連續 3 次未完成，已停止自動重試」。model `TranscriptionQueue` 加欄位。驗收 = 單元測試覆蓋「第 3 次 revert 變 failed、前 2 次回 pending」
- [x] 2.3 重置點兩處：後台 retry endpoint 將 failure_count 歸 0；`_mark_queue_finished(completed)` 亦歸 0。驗收 = 單元測試覆蓋兩個重置情境
- [x] 2.4 後台 queue UI 確認 terminal failed row 的 error_message 可見（既有 failed 卡片機制應直接吃到，不改 UI 只驗證；若訊息未顯示則補）

## 3. Dispatcher：external row 短路（D3）

- [x] 3.1 實作 spec「Dispatcher never dispatches ASR for externally imported rows」：backend/app/workers/dispatcher.py `_try_pop_one`（或 pop 後檢查）：`whisper_model` 以 `external:` 開頭的 row 標 failed + error_message「外部匯入集，系統無法重跑 ASR；請重新執行 transcript-import」，不送 celery task；一般 row 行為不變。驗收 = 單元測試兩案例（external 短路 / large-v3 照派）
- [x] 3.2 確認 transcript-import endpoint 對此類 failed row 的 revive 路徑不受影響（既有 test_transcript_import.py revive 案例應全綠；補一個「dispatcher 標 failed 後 re-import 成功」的整合案例）

## 4. Deep-link 與計數（D4/D5）

- [x] 4.1 實作 spec「Single-episode endpoint」：backend/app/api/episodes.py 新增 `GET /episodes/{episode_id}`：回 EpisodeResponse（含 transcript_status LEFT JOIN 推導）、404 當不存在；掛 router（與列表同 public read 層級）。驗收 = 新增 API 測試 200/404 兩案例
- [x] 4.2 實作 spec「URL deep-link resolves episodes via the single-episode endpoint」：src/App.jsx deep-link receiver：改打 `GET /episodes/{episode_id}` 取單集（show meta 仍由 /shows 取），移除「抓列表再 find」；404/fetch 失敗維持既有靜默 fallback。驗收 = 本機手動驗證新舊兩種集數的 deep-link
- [x] 4.3 實作 spec「Episode panel transcribed count reflects the backend total」：src/QueryPage.jsx `epCount` 改用 `show.transcribed_count`，移除已載入分頁 filter 計數。驗收 = 台通查詢頁計數顯示 = 後端 transcribed_count
- [x] 4.4 Prod smoke：部署後對兩新節目各挑一集「第 51 集以後」的舊集開 `?show_id=&episode_id=&t=` deep-link 驗證落地 + 捲動；台通查詢頁計數顯示 563/565 級別的正確值；後台 queue 無異常新增 row

## 5. 部署與觀察

- [x] 5.1 部署 prod（backend + worker + 前端），確認 alembic upgrade 成功、服務 RUNNING、無啟動錯誤 log
- [x] 5.2 上線一週觀察點記入 roadmap/backlog：failure_count>=1 的 row 分佈（驗 D2 門檻 3 是否誤殺慢任務）；EP326 類事故是否歸零
