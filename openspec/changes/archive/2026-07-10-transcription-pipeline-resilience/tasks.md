## 1. B1 — sync 失效 storage key

- [x] 1.1 實作 spec「Sync show episodes endpoint」修訂：backend/app/services/sync.py `sync_show_episodes` 欄位更新迴圈——偵測既有集 `audio_url` 舊值 ≠ 新值時，除更新 `audio_url` 外一併設 `audio_storage_key = None`；其他欄位變動（title/description 等）不得觸碰 storage key；新增集路徑不變。驗收 = 新測試檔全綠 + 既有 sync 相關測試零新增失敗
- [x] 1.2 新增 backend/tests/test_sync_storage_key_invalidation.py：以 mock `fetch_and_parse` 餵固定 feed 對真實本機 Postgres 跑 `sync_show_episodes`，覆蓋 spec 兩個新 scenario——(a) audio_url 變動 → storage key 變 NULL 且 updated 計數 +1；(b) 只有 title 變動、audio_url 相同 → storage key 保留原值

## 2. T2 — 前台顯示轉錄失敗

- [x] 2.1 實作 spec「QueryPage episode panel fetches real episodes」修訂：src/QueryPage.jsx EpisodeCard 狀態 badge 改三態——`completed` → 已轉錄/Done（success）、`failed` → 轉錄失敗/Failed（danger）、其他 → 待轉錄/Pending（muted）；failed 集維持 0.45 opacity 且不可點擊（沿用既有 non-completed 行為，不另寫點擊邏輯）；zh/en 雙語文案。驗收 = 本機以假資料目視 or prod smoke（3.2）確認三態渲染

## 3. 部署與 smoke

- [x] 3.1 部署 prod（backend + 前端），服務 RUNNING、無啟動錯誤；對兩新節目之一手動 `POST /shows/{id}/sync` 一次，確認 updated 數量正常（無異常暴增）且無集數 storage key 被誤清（sync 前後 DB 抽查 `audio_storage_key IS NULL` 計數不變，因 audio_url 都沒變）
- [x] 3.2 Prod smoke（T2）：挑一集 transcript failed 的集數（如無現成，用 admin 對一集廢棄測試集觸發或以 prod PG 寫入 SOP 暫設一筆 transcripts.status='failed' 再還原）確認前台集數卡顯示「轉錄失敗」danger badge 且不可點擊；完成後還原測試資料
