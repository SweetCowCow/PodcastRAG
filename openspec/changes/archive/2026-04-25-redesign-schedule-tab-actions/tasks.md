## 1. UI 結構與選取狀態

- [x] 1.1 在 `src/AdminPage.jsx` 的 `ScheduleTab` 元件中新增 `selectedIds` state（`Set<string>`），實作 `toggleSelect(showId)`、`clearSelection()`、`selectAll(allShowIds)` 三個 helpers — 對應「ScheduleTab supports row selection for batch operations」需求
- [x] 1.2 移除 `ScheduleTab` 頂端的「同步所有」按鈕、`handleSyncAll` 函式、`syncing` state — 對應「ScheduleTab frontend fetches real data」中 legacy Sync All 移除規範
- [x] 1.3 在每張節目卡片左側渲染選取 checkbox（取代原本的 enable toggle 圓鈕），並在卡片清單上方加入「全選 / 已選 N 個 / 取消選取」master row — 對應「Admin schedule card exposes show-level actions」與「ScheduleTab supports row selection for batch operations」
- [x] 1.4 當 `selectedIds.size > 0` 時於頁面頂端條件渲染批次操作列（含計數、批次「更新節目集數」、批次「轉錄未完成集數」、「取消選取」）；空集合時不渲染整列 — 對應「ScheduleTab supports row selection for batch operations」

## 2. 卡片按鈕重組與「⋯」選單

- [x] 2.1 在 `src/Shared.jsx` 新增（或沿用既有 pattern）一個 `OverflowMenu` 元件，接收 `items: { label, icon?, onClick, disabled? }[]`，預設關閉、點擊背景或 ESC 關閉 — 給 `ScheduleTab` 卡片的「⋯」按鈕使用
- [x] 2.2 把節目卡片右側的「同步集數」、「編輯排程」、「移除排程」、「刪除節目」按鈕改為單一「⋯」overflow 入口；條目順序固定：「更新節目集數」、「編輯排程」、「移除排程」、「刪除節目」 — 對應 modified 的「Admin schedule card exposes show-level actions」
- [x] 2.3 確保 `schedule == null` 的卡片其「⋯」選單僅顯示「更新節目集數」與「刪除節目」兩條；同時不渲染「立刻執行」按鈕 — 對應「Admin schedule card exposes show-level actions」中「Card without schedule hides schedule-only entries」scenario
- [x] 2.4 把現有 `handleSyncShow`（單節目「同步集數」）綁到「⋯」的「更新節目集數」條目，行為不變（非破壞性、不彈 confirm、loading 期間禁用條目）— 對應 modified 的「Sync Episodes is non-destructive and requires no confirmation」（含按鈕重命名為「更新節目集數」）

## 3. enable toggle 移到「編輯排程」modal

- [x] 3.1 從卡片版面移除 `handleToggle` 對應的 enable toggle 圓鈕 DOM（保留 `handleToggle` 函式給 modal 內使用，如有需要可重命名）— 對應「ScheduleTab frontend fetches real data」中「Legacy in-card toggle is removed」scenario
- [x] 3.2 在「編輯排程」modal 表單內新增「自動轉錄」欄位（label + 一個 toggle/switch 控件），值綁到表單 state 的 `enabled` 欄位；底下加入提示文字「待 cron 功能上線後生效」/ "Takes effect once cron support ships." — 對應「ScheduleTab frontend fetches real data」中「Auto Transcribe field appears in Edit Schedule modal」scenario
- [x] 3.3 將 modal 的 `handleSaveEdit` 函式擴充，於 `PUT /shows/{show_id}/schedule` 的 payload 中包含 `enabled` 欄位；存檔成功後重抓 `GET /admin/schedules` — 對應「ScheduleTab frontend fetches real data」中「Saving the Edit Schedule modal persists enabled」scenario

## 4. 批次操作 — 更新節目集數

- [x] 4.1 新增 `handleBatchRefreshEpisodes()`：對 `selectedIds` 中每個 show 並行 `POST /shows/{id}/sync`，使用 `Promise.allSettled`；期間設 `batchRefreshing=true` 禁用按鈕 — 對應「Batch Refresh Episodes fans out per selected show」
- [x] 4.2 完成後彙整 fulfilled responses 的 `added`、`updated` 總和，連同失敗節目清單顯示在單一 alert/toast；接著 `loadSchedules()` 重抓清單，**不清空** `selectedIds` — 對應「Batch Refresh Episodes fans out per selected show」中「aggregates results」「Selection persists after batch refresh」scenarios

## 5. 批次操作 — 轉錄未完成集數（含 confirm）

- [x] 5.1 新增 `batchTranscribeConfirmOpen` state；點擊批次「轉錄未完成集數」時 set true、開啟 `ConfirmModal`，內文「即將對 N 個節目排入轉錄，會消耗 OpenAI 額度，是否繼續？」/ 對應英文版本，按鈕「確認 / Confirm」、「取消 / Cancel」 — 對應「Batch Transcribe Pending requires confirmation and respects per-show max_episodes」中 confirmation modal scenarios
- [x] 5.2 點「取消」或關閉 modal 時 set `batchTranscribeConfirmOpen=false`，**不發任何 request** — 對應「Cancel aborts the batch transcription」scenario
- [x] 5.3 點「確認」後執行 `handleBatchTranscribePending()`：對 `selectedIds` 中每個 show 並行 `POST /shows/{id}/transcribe-latest`（**不傳 `max_episodes` query**，使用各自 schedule.max_episodes）；期間禁用按鈕；完成後彙整 `queued` 總和與失敗節目顯示於單一 alert，接著 `loadSchedules()` — 對應「respects per-show max_episodes」與「Confirm fans out one request per selected show」scenarios
- [x] 5.4 確認單卡「立刻執行」（`handleRunNow`）行為不變、不彈批次 confirm modal — 對應「Single-show 立刻執行 still skips the confirm modal」scenario

## 6. 文案與 i18n

- [x] 6.1 集中檢視 `ScheduleTab` 內所有與「同步」相關的字串，全面替換為「更新節目集數」/「Refresh Episodes」與「轉錄未完成集數」/「Transcribe Pending」；保留「立刻執行」/「Run Now」單卡按鈕 — 確保 modified 的「Admin schedule card exposes show-level actions」與 modified 的「Sync Episodes is non-destructive and requires no confirmation」用詞一致
- [x] 6.2 為「自動轉錄」欄位的 helper text 提供 zh / en 雙語字串：「待 cron 功能上線後生效」/ "Takes effect once cron support ships."

## 7. 手動驗證

- [x] 7.1 在瀏覽器手動驗證：建立 ≥ 2 個節目（含至少一個 `schedule=null`），確認卡片版面、checkbox、⋯ 選單條目、批次操作列在「無選取 / 部分選取 / 全選」三種狀態下都符合 spec；驗證 `schedule=null` 卡片不顯示「立刻執行」也不顯示「編輯排程 / 移除排程」
- [x] 7.2 手動驗證批次「更新節目集數」：對 2 個節目觸發、檢查 Network panel 確實發 2 個 `POST /shows/{id}/sync`、aggregated alert 顯示 added/updated 總和、選取仍保留
- [x] 7.3 手動驗證批次「轉錄未完成集數」：confirm modal 出現且文案含「N 個節目」、按取消不發 request、按確認後對每個節目發出 `POST /shows/{id}/transcribe-latest`（無 `max_episodes` query 參數）
- [x] 7.4 手動驗證「自動轉錄」欄位：在「編輯排程」modal 內可切換、helper text 正確顯示、按存檔後 `PUT /shows/{id}/schedule` payload 含 `enabled` 新值；重抓清單後該值仍正確

## 8. Prod 驗證後發現的 UX 問題（ingest 加入）

- [x] 8.1 在 `src/AdminPage.jsx` 中將「立刻執行」/「Run Now」按鈕文案、disabled 狀態文案（`執行中... / Running...`）、相關 i18n 字串全面改成「立刻執行轉錄」/「Run Transcribe Now」 — 對應 modified 的「Admin schedule card exposes show-level actions」與「Single-show 立刻執行轉錄 still skips the confirm modal」scenario
- [x] 8.2 在 `src/AdminPage.jsx` 中把 `ScheduleTab` 頁面頂端按鈕從「新增排程」/「Add Schedule」改名為「新增節目」/「Add Show」；同時將「新增轉錄排程」/「New Transcription Schedule」表單面板標題改名為「新增節目轉錄排程」/「New Show with Transcription Schedule」 — 對應新 requirement「ScheduleTab page header uses Add Show language」
- [x] 8.3 在 `src/AdminPage.jsx` 的 `ScheduleTab` 內新增 `handleOpenAddSchedule(item)`：針對 `schedule == null` 的卡片，重用 `editState`（沿用 `handleSaveEdit` 走 `PUT /shows/{id}/schedule`）並預填預設值 `{enabled:false, frequency:'manual', run_time:'06:00', whisper_model:'large-v3', max_episodes:0}`；同時於 schedule=null 卡片的 ⋯ overflow menu 第一條加入「新增排程」/「Add Schedule」項目綁到此 handler — 對應新 requirement「Add Schedule from card without schedule」
- [x] 8.4 在瀏覽器（Zeabur prod）驗證 issue 1：對 prod 一個有 schedule 的節目按「⋯ → 移除排程」造出 schedule=null 狀態，確認 ⋯ 選單出現「新增排程 / 更新節目集數 / 刪除節目」三條，且「立刻執行轉錄」按鈕不顯示；點「新增排程」開啟 modal、預設值正確、儲存後 PUT 成功、卡片刷新出現 schedule。驗證後將該節目的 schedule 還原為原本設定（enabled / frequency / run_time / whisper_model / max_episodes）— 對應 Add Schedule from card without schedule + 兩條 Card without schedule scenarios
- [x] 8.5 在瀏覽器（Zeabur prod）驗證 issue 2 + 3：頂端按鈕顯示「新增節目」、點開後面板標題顯示「新增節目轉錄排程」；任意 schedule != null 卡片的「立刻執行轉錄」按鈕文字正確、點擊後 alert 行為照舊不變 — 對應「ScheduleTab page header uses Add Show language」與「Single-show 立刻執行轉錄 still skips the confirm modal」

