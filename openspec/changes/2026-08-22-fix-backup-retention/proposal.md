## Why

2026-08-22 於 Cloudflare 面板發現備份 bucket `podcastrag-backup` 累積到 **108 物件 / 520.85 GB**
（實測物件列表 472.80 GB，差額為不列在列表中但照常計費的 multipart 殘件）。

`2026-05-07-db-backup` 的設計承諾是「daily 7 + weekly 4 + monthly 12 ≈ 23 份、約 12 GB-month、月費 ~$0.5」。
實際狀況是設計值的 **4.7 倍物件數、43 倍容量**，月費約 **$7.8**（$0.015/GB）。

上線 107 天、daily 物件 107 份 → **每日備份全數留存，保留策略從第一天起就沒有生效過，
而且整整 3.5 個月沒有任何機制發現它沒生效。**

同時查核排除了兩個無關因素：
- 音檔 bucket `podcastrag` 實測 **0 物件 / 0 bytes**、無殘留 multipart → 2026-07-24 那次清 63.6 GB 與自動刪音檔機制運作正常，本問題與轉錄殘留無關
- `task_failure_log` 查無任何 `db_backup` 失敗紀錄 → 備份任務本身「看起來」一直是成功的

真正的風險不只是錢。**沒有人知道保留策略壞掉，是因為沒有任何東西在看它。**
同一個盲區下，備份數量爆增 43 倍這種明顯異常都能靜默 3.5 個月，
代表現行的「size anomaly 日對日比值告警」對緩慢累積型的故障完全無效。

### 2026-08-22 維運與複查取得的四項新事實

本 change 起草後，實地清理存量並複查 artifacts，取得以下實測結果（均非推論）：

1. **lifecycle 未生效的機制已確認**：`GetBucketLifecycleConfiguration` 實測回 **AccessDenied**。
   R2 API token 只有 Object 層權限，讀寫 bucket 層設定都會被拒。
   這使得原設計「read-back 驗證失敗即告警」會**每天發出一封收信者無法處理的告警**
   （要到 Cloudflare dashboard 換 token 才能解），本身就是告警疲勞的來源。
   app 端清掃因此不是「第二層防線」而是**現階段唯一可行的保留機制**。

2. **容量數字全面過時**：單份 dump 實測 **7.07 GiB**（7,592,936,742 bytes），
   非原文件記載的 4.82 GB，三個月成長約 47% 且仍在長。
   修好後穩態應為 23 份 × 7.07 GB ≈ **163 GB ≈ $2.44/月**（原文件寫 110 GB / $1.65）。

3. **【新增根因】備份任務每天實際重複執行 3 次**。三條獨立證據：
   - Redis result backend 中 2026-08-21 的備份結果 `duration_ms = 7,656,611` → **2 小時 7 分鐘**
   - `celery_app.py` 設 `task_acks_late=True`，但 `broker_transport_options` 未設
     `visibility_timeout`；worker 容器實測 kombu 預設值為 **3600 秒**
   - 清理時 abort 的 4 件 multipart 殘件時間戳間隔**正好整點 1 小時**，而 beat 只排 03:00 一次

   → 任務執行時間超過 visibility_timeout 而未 ack，被 Redis 重新投遞，
   三個 pg_dump 並行打 prod DB、各自上傳 7.5 GB 覆寫同一 key，未完成者留下 multipart 殘件。
   **這推翻了原本「殘件來自 worker 被 SIGKILL（redeploy／OOM）」的假設**，
   殘件是重投的副產物，abort 清掃只治症狀。

4. **既有存量已於 2026-08-22 清除完畢**（原列為本 change 之外的維運操作）：
   108 物件 / 472.80 GB → 12 物件 / 64.01 GB，4 件 multipart 殘件全數 abort。
   其後另將 4 個補位月錨促級到 `monthly/` 前綴，現況 daily 11 + weekly 1 + monthly 4 = 16 份。
   證據留存於 `docs/case-studies/r2-cleanup-2026-08-22/`。

## What Changes

修正保留機制本身、消滅重複執行的根因，並補上「保留策略有沒有真的生效」的監測：

- **消滅任務重投（根因）**：`celery_app.py` 的 `broker_transport_options` 增加
  `visibility_timeout: 14400`（4 小時），使執行 2 小時餘的備份任務不再被 Redis 重新投遞。
  副作用（worker 真的死亡時任務重投變慢）由 `cron_tick` 既有的
  `stale_marked` / `orphans_reverted` 機制承接。
- **新增 app 端保留清掃**：不再依賴 bucket lifecycle。每次備份後列舉各 prefix，
  超出 7/4/12 的物件由程式刪除，並 abort 逾期的 multipart uploads。
  清掃設**單次刪除上限**保險閥：刪除數超過上限時只告警不刪，需人工介入。
  批次 `delete_objects` 的 `Errors` 陣列必須檢查——它回傳錯誤而不拋例外，
  逐 key 失敗若不檢查就會重演「靜默的保留失效」。
- **lifecycle 降級為 best-effort 且不重複告警**：`_LIFECYCLE_RULES` 仍補上
  `AbortIncompleteMultipartUpload`（`PutBucketLifecycleConfiguration` 是整組覆寫語意，
  現行 3 條規則會抹掉 R2 建 bucket 時預設的 7 天 abort 規則），
  但因 token 權限已知不足，套用與 read-back 驗證改為**狀態轉換時才告警一次**，
  不再每日重發無法處理的告警。
- **weekly/monthly 促級改用 size-aware managed copy**：`copy_object` 單次上限 5 GiB，
  dump 已達 7.07 GB **確定超過**。改用 `client.copy()`（已在 R2 上實測可複製 7.00 GB 物件成功），
  整段包 try/except，失敗只告警不拋錯——現行 `db_backup.py` 促級段無任何錯誤處理，
  失敗會讓已上傳成功的當日備份任務拋錯並觸發 Celery retry。
- **新增 bucket 用量守門**：每次備份後統計物件數與總容量，超出預期上限即 ZSend 告警。
  這是本 change 的核心——讓「保留策略壞掉」變成一件會被發現的事。

## Non-Goals

- **縮小 dump 本身**：修好保留後約 23 份 × 7.07 GB ≈ 163 GB ≈ $2.44/月，仍在原設計 $5/月上限內。
  排除 `transcript_chunks` 的 embedding 資料雖可大幅縮小，但會讓備份不再是完整可還原快照，違背 DR 目的，不做。
- **調查 `transcribe` 等其他長任務是否也曾被重投**：`visibility_timeout` 的修正對所有 queue 生效，
  但「過去是否已造成重複轉錄」需要另行盤查 DB 與計費紀錄，列為 follow-up，不在本 change 範圍。
- **升級 R2 API token 權限**：讓 lifecycle 真正可用需到 Cloudflare dashboard 換發
  Admin Read & Write token，屬人工維運動作，列為部署後的可選項而非本 change 的阻塞項。
- **改變 RPO/RTO 承諾**：維持 RPO ≤ 24h、RTO ≤ 30 min。
- **改變加密方案**：age 公鑰加密維持不變。
- **改變備份頻率**：維持每日 03:00 UTC。

## Capabilities

### Modified Capabilities

- `db-backup-pipeline`：保留策略執行、lifecycle 驗證、用量守門、任務重投防護

## Impact

- Affected specs: `db-backup-pipeline`（修改）
- Affected code:
  - Modified:
    - `backend/app/workers/celery_app.py` — `broker_transport_options` 增加 `visibility_timeout`
    - `backend/app/services/r2_backup_client.py` — `_LIFECYCLE_RULES` 加 `AbortIncompleteMultipartUpload`；
      新增 `verify_lifecycle_policy()`、`sweep_retention()`、`abort_stale_multipart_uploads()`、`bucket_usage()`
    - `backend/app/workers/db_backup.py` — lifecycle 套用改為驗證＋狀態轉換告警；促級改 managed copy 並包 try/except；
      備份後呼叫保留清掃與用量守門
    - `backend/tests/test_celery_routing.py` — 補 `visibility_timeout` 設定的測試
      （既有 `test_broker_priority_steps_for_redis` 已在驗 `broker_transport_options`）
    - `backend/tests/test_r2_backup_client.py` — 補 lifecycle 規則、清掃、用量統計的測試
    - `backend/tests/test_db_backup.py` — 補驗證失敗告警、促級失敗不影響當日備份、用量超標告警的測試
    - `docs/disaster-recovery.md` — 補「如何確認保留策略生效」與人工清掃步驟
  - New: (none)
  - Removed: (none)
