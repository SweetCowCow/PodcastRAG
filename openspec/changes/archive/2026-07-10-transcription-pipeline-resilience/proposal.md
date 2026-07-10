## Problem

轉錄管線在「來源檔更新」與「失敗透明度」兩處缺韌性，都是 2026-07-01 EP20 壞源檔事件的直接教訓（均已對現行源碼 1:1 驗證）：

1. **B1 — 來源檔更新後系統仍用舊壞檔**：worker 轉錄一律從 R2 的 `audio_storage_key` 下載（不是 `audio_url`）。當節目作者重新上傳修正版音檔（EP20 實例），RSS re-sync（`backend/app/services/sync.py` 的 `sync_show_episodes`）只把新 `audio_url` 寫回 DB，`audio_storage_key` 原封不動 → 之後任何重試都還是抓 R2 上的舊壞檔，永遠失敗。EP20 當時靠人工把 `audio_storage_key` 清 NULL 才解。
2. **T2 — 轉錄失敗對使用者隱形**：episodes API 已回傳 `transcript_status`（含 `failed` 值），但前台集數卡（`src/QueryPage.jsx` 的 EpisodeCard）是二元判斷：`completed` → 「已轉錄」、其他一律「待轉錄」。轉錄失敗的集永遠掛「待轉錄」，使用者不知道它壞了、也不會知道系統已停止重試（worker-reliability D2 上線後 failed 是明確終止態，前台更該誠實顯示）。

## Root Cause

- B1：`sync_show_episodes` 的欄位比對迴圈把 `audio_url` 當普通 metadata 更新，沒有意識到它是 `audio_storage_key` 的上游——兩者從此脫鉤。
- T2：前台狀態 badge 寫在只有 completed/pending 兩態的年代，後來 `failed`（以及 `processing`）進了 API contract 但 UI 沒跟上。

## Proposed Solution

1. **B1**：`sync_show_episodes` 欄位更新迴圈中，偵測到 `audio_url` 值變動時，一併把該集 `audio_storage_key` 設為 NULL——下一次轉錄（手動 retry 或 schedule enqueue）自然重新從新 URL 抓檔上傳 R2。只在「既有集、audio_url 舊值 ≠ 新值」時觸發；新增集本來就無 storage key。
2. **T2**：EpisodeCard 狀態 badge 從二元改三態：`completed` → 「已轉錄」（success）、`failed` → 「轉錄失敗」（danger）、其他（null / pending / processing）→ 「待轉錄」（muted，維持現狀）。failed 集維持不可點擊（無逐字稿可看）。不透露失敗原因細節——原始 error_message 可能含內部資訊（provider 名、檔案路徑），細節留在後台 queue 卡片。

## Non-Goals

- 不做 enclosure length / 版本戳比對——`audio_url` 字串變動已覆蓋 EP20 實際情境（作者重傳通常換 URL）；同 URL 換內容的邊角情境無可靠偵測訊號，不在本次範圍。
- 不自動重新 enqueue 轉錄——失效 storage key 後由既有路徑（手動 retry / schedule）觸發，避免 sync 走到哪轉錄費燒到哪。
- 前台不顯示失敗原因細節（error_message 白名單過濾另議）；後台 queue 已有完整訊息。
- 不動後台「轉錄排程」頁 pending_count 的計算口徑（把 failed 算 pending 的帳面小瑕疵，等有人反映再說）。

## Success Criteria

1. 單元測試：sync 對既有集更新 `audio_url` → 該集 `audio_storage_key` 變 NULL；`audio_url` 未變 → storage key 不動；新增集路徑不受影響（既有 sync 測試零新增失敗）。
2. 單元測試：title/description 變動但 `audio_url` 未變 → storage key 保留（不誤殺）。
3. 前台：`transcript_status='failed'` 的集數卡顯示「轉錄失敗」danger badge、不可點擊；`completed`／其他狀態顯示不變（zh/en 雙語）。
4. Prod smoke：找一集 failed（或以 DB 設一集測試值）確認前台顯示；sync 一個節目確認無異常 updated 暴增。

## Impact

- Affected code:
  - Modified: backend/app/services/sync.py, backend/tests/test_sync_service.py（若不存在則列入 New）, src/QueryPage.jsx
  - New: backend/tests/test_sync_storage_key_invalidation.py
  - Removed: （無）
