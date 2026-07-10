## Problem

2026-07-10 EP326 匯入卡死事故（卡 14 小時、每 4 分鐘無限重派）的 RCA 挖出四個彼此疊加的既有 bug，全數已對源碼 1:1 驗證：

1. **permanent-fail handler 炸 NameError，失敗永遠標不上**：`backend/app/workers/tasks.py` 的 `_run` 是 module-level async 函式，但其 PERMANENT_ERRORS except 區塊引用了不存在的 `self`（`record_task_failure(..., retry_count=int(self.request.retries or 0))`）。任何 permanent ASR 錯誤（壞音檔、ffmpeg 失敗等）都會在 handler 內拋 NameError，跳過後面「transcript 標 failed + queue row 標 failed」的收尾。2026-05-18 task-failure-monitoring change（df31d6a）遺留。
2. **queue row 因此進入無限重派迴圈**：收尾沒跑到 → row 卡 running → cron 的 orphan-revert 把它打回 pending → dispatcher 再派 → 再炸 → 循環（EP326 實測每 ~4 分鐘一輪）。即 backlog B2「壞檔無限重試該有終止狀態」的直接成因之一；B2 另需「連續失敗 N 次 → terminal」的獨立保險。
3. **import 路徑的 row 會被 dispatcher 錯派到 ASR**：`backend/app/workers/dispatcher.py` 對 pop 出的 pending row 無條件送 `app.workers.tasks.transcribe_episode`。外部匯入節目（queue `whisper_model` 為 `external:` 前綴）的 import task 若遺失（容器重啟），復活的 pending row 會走 ASR 下載音檔跑 whisper——白繞流程、可能白燒 API 錢（EP326 幸運在 ffmpeg 階段就失敗）。
4. **逐字稿 deep-link 超過最新 50 集靜默失效**：`src/App.jsx` deep-link receiver 抓 `GET /shows/{show_id}/episodes`（預設 `limit=50`）後 `eps.find(episode_id)`，找不到就靜默 fallback 回首頁。任何節目第 51 集以後的分享連結全部失效——曼報（575 集）時代就存在，被塞掐（449 集）/台通（565 集）上線放大。附帶同家族小症狀：查詢頁右欄「已轉錄集數」用已載入分頁計數當分子（`src/QueryPage.jsx` 的 `epCount`），顯示 197/565 這類誤導數字。

## Root Cause

- Bug 1/2：把 bound-method 語境的程式碼搬進 module-level 函式時未同步改 `self` 引用；且 permanent-fail 收尾與失敗記錄耦合在同一個 try 流程，記錄炸掉會連帶跳過狀態收尾。
- Bug 3：dispatcher 設計時只有單一 ASR 任務型別，匯入路徑（2026-07 新增）的 row 復活情境未被涵蓋。
- Bug 4：deep-link receiver 用「抓列表再 find」實作單集查詢，列表 API 天生分頁；前端計數同樣把「已載入的分頁」當成全集合。

## Proposed Solution

依影響面由小到大、可獨立驗證的四段修復（實作細節進 design/tasks 時定案，以下為方向）：

1. **NameError 一行修 + 收尾保底**：permanent-fail 區塊拿掉 `self` 引用（retry_count 取 0 或由外層傳入）；並把「transcript/queue 標 failed」包在 `record_task_failure` 之前或 finally 化，確保記錄失敗不再吞掉狀態收尾。
2. **連續失敗終止狀態（B2）**：queue row 連續失敗達門檻（建議 3 次）→ 標 terminal `failed` 且 orphan-revert / stale-detect 不再復活；後台 queue UI 可見、可手動 retry。
3. **dispatcher 對 `external:` row 不派 ASR**：pop 到 `whisper_model` 為 `external:` 前綴的 row 時不送 `transcribe_episode`，直接標 failed 附「需重新匯入」訊息（匯入來源資料在站外，系統無法自行重跑）。
4. **deep-link 改走單集查詢 + 計數修正**：新增 `GET /episodes/{episode_id}`（回單集 + transcript_status + 所屬 show）；`App.jsx` deep-link receiver 改打單集 endpoint，任何歷史集的分享連結都能落地；`QueryPage.jsx` 的 `epCount` 在集數未全載時 fallback 用 `show.transcribed_count`。

## Non-Goals

- 不做 import task 的自動重試 / 自動重匯（來源 JSON 在本機，系統端無從取得；標 failed + 訊息即可）。
- 不動 B1（RSS re-sync 偵測 audio_url 變動失效 storage key）——另案處理。
- 不做 episodes 列表的無限捲動 / 全量載入重構；只修 deep-link 與計數兩個消費點。
- 不改 orphan-revert / stale-detect 的偵測邏輯本體，只加 terminal 狀態讓它們有停下來的條件。

## Success Criteria

1. 對一個壞音檔 episode 觸發 permanent 錯誤：transcript 標 `failed`、queue row 標 `failed`、不再被重派（觀察 ≥ 3 個 cron tick 週期零新 celery task）；`task_failures` 記錄成功寫入。
2. 單元測試覆蓋：permanent-fail 收尾在 `record_task_failure` 拋例外時仍完成標記。
3. 連續失敗 3 次的 row 進 terminal failed，後台 UI 顯示且 orphan-revert 略過；手動 retry 後計數歸零。
4. `external:` row 進 pending 後被 dispatcher 標 failed（訊息含「重新匯入」），無 `transcribe_episode` task 產生。
5. 對兩新節目第 51 集以後的任一集開 `?show_id=…&episode_id=…&t=…` deep-link：直接落在該集逐字稿頁並捲到時間點（手動 smoke + 前端單元不易，驗收以 prod smoke 為準）。
6. 台通查詢頁右欄計數顯示 563/565（= `transcribed_count`），不再是已載入分頁數。

## Impact

- Affected code:
  - Modified: backend/app/workers/tasks.py, backend/app/workers/dispatcher.py, backend/app/workers/cron_tick.py, backend/app/api/episodes.py, backend/app/models/transcription_queue.py（若終止態需新欄位）, src/App.jsx, src/QueryPage.jsx, backend/tests/test_transcript_import.py（新增情境）
  - New: backend/tests/test_permanent_fail_terminal.py
  - Removed: （無）
