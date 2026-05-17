## 1. Backend endpoint

- [x] 1.1 寫 `backend/app/api/admin_processing_stats.py` 暴露 `GET /admin/processing-stats`：用 SQL 算 transcription / summary / topic_seg 三維度的 episode + segment count、24h delta、failures from Celery result backend；admin role gate + CSRF（落實 Requirement: Processing stats admin endpoint）
- [x] 1.2 註冊 router 進 `backend/app/main.py`
- [x] 1.3 寫 `backend/tests/test_admin_processing_stats_api.py`：覆蓋 4 個 scenario（response shape / topic_seg dual count / 24h failures grouped / non-admin 403）
- [x] 1.4 在 endpoint 內預留 `_fetch_failures()` switch：v1 從 Celery result backend 撈，註解標明 F2 archive 後改 task_failure_log（同 schema 包裝）

## 2. Admin UI

- [x] 2.1 在 `src/QueueTab.jsx` 加新 `<ProcessingOverview>` 子元件（同檔案內或抽到 `src/ProcessingOverview.jsx`）：fetch /admin/processing-stats、render 三個 progress bar、24h section、上次更新 timestamp（落實 Requirement: Admin Queue Tab shows processing overview）
- [x] 2.2 progress bar 用純 CSS：`<div style={{width: ratio+'%', background: TOKEN.accent}}>`，不裝 chart library（落實 Non-Goal "不引入新 chart library"）
- [x] 2.3 topic_seg row 顯示 segment 主數 + episode 副數（muted secondary text）
- [x] 2.4 「查看失敗清單」展開 button + inline table render task_name × count × sample_error
- [x] 2.5 setInterval 30s polling；poll 失敗顯示「更新失敗，重試中...」warning text（不影響底下 queue table）
- [x] 2.6 雙語 i18n（zh primary + en key per CLAUDE.md）：「進度概覽 / Processing Overview」「轉錄 / Transcription」「摘要 / Summary」「分類 / Topic」「最近 24 小時 / Last 24 Hours」「查看失敗清單 / Show Failures」「上次更新 / Last Updated」
- [x] 2.7 ProcessingOverview 插入 QueueTab 最上方（既有 queue table 之上）

## 3. 部署 + smoke

- [x] 3.1 commit + push → Zeabur backend redeploy
- [x] 3.2 admin 開 Queue Tab → 三個 progress bar 顯示對 + 數字跟手動 SQL query 對得上
- [x] 3.3 觀察 30s polling：等 30 秒 + 觸發新轉錄完成，數字應自動更新
- [x] 3.4 故意把網路斷一下（或關掉 backend）→ 確認 warning text 出現 + queue table 仍可見
- [x] 3.5 release log 補對應 entry：「admin Queue Tab 上方多了「進度概覽」，三個 progress bar 看轉錄 / 摘要 / 分類進度，30 秒自動更新」
