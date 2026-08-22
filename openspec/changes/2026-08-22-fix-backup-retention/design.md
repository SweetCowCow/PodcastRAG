## Context

`2026-05-07-db-backup` 上線後從未被稽核過。2026-08-22 清點結果：

| 項目 | 設計值 | 實際 | 倍數 |
| --- | --- | --- | --- |
| 物件數 | ≈ 23 | 108 | 4.7× |
| 容量 | ≈ 12 GB | 472.80 GB（面板計費 520.85） | 39× |
| 月費 | ~$0.5 | ~$7.8 | 15.6× |

上線 107 天、daily 物件 107 份 → **每日備份全數留存，保留策略從未生效**。

旁證（已實測排除的因素）：
- 音檔 bucket `podcastrag`：0 物件 / 0 bytes，無殘留 multipart，lifecycle 上仍有 R2 預設的
  `Default Multipart Abort Rule`（`DaysAfterInitiation: 7`）
- prod DB 現況 15 GB（`transcript_chunks` 14 GB）、1624 集全 `completed`、`audio_storage_key IS NOT NULL` 為 0 筆
- `task_failure_log` 無任何 `db_backup` 紀錄

DB 從設計時預估的 1-2 GB 長到 15 GB，dump 也從預估的 300-700 MB 長到 **7.07 GiB**
（2026-08-21 實測 7,592,936,742 bytes；三個月前約 4.8 GB，成長 47%）。
這個成長本身是正常的，但它讓所有原本「小到可以忽略」的缺陷同時放大——
最關鍵的是它讓單次備份的執行時間跨過了 Celery 的 visibility_timeout 門檻（見 Decision 6）。

### 2026-08-22 維運與複查後的事實更新

本文件起草後取得的實測結果，已反映在下方各 Decision：

- `GetBucketLifecycleConfiguration` 回 **AccessDenied** → 原「待釐清」的兩個候選定案為
  **(a) token 權限不足**（見 Decision 2）
- 備份任務 2026-08-21 實測 `duration_ms = 7,656,611`（2 小時 7 分）
  → 超過 kombu 預設 visibility_timeout 3600 秒（見 Decision 6，本次新增）
- boto3 managed `client.copy()` 已在 R2 上實測可複製 7.00 GB 物件（見 Decision 4）
- 既有存量已清除完畢（見附錄）

## Goals / Non-Goals

### Goals
- 保留策略確實生效，穩態物件數收斂到 23 份以內
- 保留策略「沒生效」這件事本身會在 24 小時內被發現並告警
- 備份任務每天只執行一次，不再因任務重投而並行多份 pg_dump
- 未完成的 multipart 上傳不會無限期計費
- 促級（weekly/monthly）失敗不得污染已成功的當日備份

### Non-Goals
- 縮小 dump、改頻率、改加密、改 RPO/RTO（見 `proposal.md`）
- 盤查 `transcribe` 等其他長任務過去是否已因重投而重複執行（follow-up）
- 升級 R2 API token 權限（人工維運動作，部署後可選）

### 範圍邊界

**在範圍內**：`backend/app/workers/celery_app.py` 的 broker 設定、
`backend/app/services/r2_backup_client.py` 的 R2 操作 helper、
`backend/app/workers/db_backup.py` 的備份任務流程、對應測試、`docs/disaster-recovery.md`。

**不在範圍內**：其他 worker task 的行為調整、Celery queue 拓樸、
R2 token 的換發、音檔 bucket（`app.services.storage`）的任何設定。
`visibility_timeout` 是 broker 層設定，效果及於所有 queue——本 change 只承諾
「備份任務不再重投」，其他 task 的既有行為變化列為 follow-up 觀察項。

## Decisions

### Decision 1: 保留執行改為「app 端清掃為唯一機制、bucket lifecycle 為 best-effort」

**選擇**：每次備份成功後，程式列舉 `daily/`、`weekly/`、`monthly/` 三個 prefix，
依 key 內含的日期排序，保留最新 7 / 4 / 12 份，其餘 `delete_objects` 刪除。

**Why**：
- 原設計把保留完全外包給 bucket lifecycle（`r2_backup_client.py` 的 `_LIFECYCLE_RULES`
  上方註解明寫 "the app does not need to walk and delete artifacts"）。這是單點依賴，
  而且它失效時**完全無聲**——正是這次的故障模式。
- 實測已知 token 無 bucket 層權限（Decision 2），**lifecycle 這層現階段根本拿不到**。
  原文件寫的「兩層防線」實際上只有一層，措辭已據實修正。
- app 端清掃的結果是可觀測的：刪了幾個、剩幾個，都能寫進 log 與告警。
- 物件數只有數十到一百多，列舉成本可忽略（`list_objects_v2` 一兩次分頁）。

**Alternatives considered**：
- 只修 lifecycle 規則、繼續單靠它：在 AccessDenied 的前提下不可能成立
- 先換 token 再單靠 lifecycle：把修復時程綁在人工 dashboard 操作上，且仍是單點依賴

### Decision 2: lifecycle 套用與驗證改為「狀態轉換時才告警一次」

**選擇**：`apply_lifecycle_policy()` 之後呼叫 `GetBucketLifecycleConfiguration`，
比對回傳的 rule ID 集合是否涵蓋預期的 4 條（3 條 Expiration + 1 條 Abort）。
結果（成功／失敗）與上一次的結果比較，**只有在狀態改變時才發 ZSend 告警**，
其餘情況記 log。任何情況都**不中止備份**。

**Why**：
- 原設計是「不符或拋錯即告警」。但實測 token 無 bucket 權限，
  apply 與 read-back **每天都會 AccessDenied** → 每天一封收信者無法處理的告警。
  本 change 的目的是讓真正的異常被看見，製造每日固定噪音會直接摧毀這個目的。
- 狀態轉換告警保留了偵測能力：token 若被修好（AccessDenied → OK）會通知，
  若原本正常後來壞掉也會通知，但穩定的已知失敗不會重複打擾。
- read-back 同時涵蓋「寫入被拒」與「寫入成功但語意不符預期」兩種失效。
- 不中止備份：保留策略壞掉是成本問題，備份沒做才是資料問題，兩者嚴重性不對等。

**狀態的持久化**：以 R2 上一個小物件（例如 `_state/lifecycle_verify.json`）記錄上次結果，
避免依賴 worker 記憶體（容器隨時可能被重啟，in-process 狀態不可靠）。
該 key 不符 `<prefix>/YYYY-MM-DD.dump.age` 格式，因此清掃會自動略過它（Decision 1 的格式過濾）。

### Decision 3: lifecycle 規則補 `AbortIncompleteMultipartUpload`

**選擇**：`_LIFECYCLE_RULES` 增加第 4 條，`DaysAfterInitiation: 1`。

**Why**：
- `PutBucketLifecycleConfiguration` 是整組覆寫，現行 3 條規則會抹掉 R2 預設的 7 天 abort 規則
- 殘件不列在 `ListObjectsV2` 中但照常計費，且備份失敗路徑的 `delete_object(today_key)` 刪不到它
  ——這是一個「看不見所以永遠不會被發現」的洩漏
- 1 天而非 7 天：修好 Decision 6 之後備份單次執行約 2 小時，遠短於 1 天，正常上傳不可能被誤 abort

**現況限制**：在 token 權限修好之前這條規則同樣寫不進去，
因此實際生效的是 app 端的 `abort_stale_multipart_uploads()`（見下）。
規則仍要補上，讓 token 一旦升級即自動生效。

**補充**：app 端另做一次 `list_multipart_uploads` + `abort_multipart_upload`，理由同 Decision 1
（不單押 lifecycle，且結果可觀測）。2026-08-22 清理時實地確認殘件確實存在（4 件）且可被 abort。

### Decision 4: 促級改用 size-aware managed copy 並隔離失敗

**選擇**：weekly/monthly 促級改用 `client.copy()`（boto3 managed transfer，內部自動走 multipart copy），
整段包 try/except，失敗只告警不拋錯。

**Why**：
- `copy_object` 單次上限 5 GiB，dump 已達 **7.07 GB，確定超過**（原文件寫「跨過只是時間問題」，
  實測後已成既成事實）。這解釋了為何 `monthly/` 一份都沒有、`weekly/` 只停在 2026-05-10
  ——促級從五月中 dump 長大後就一直失敗。
- **已實測驗證**：2026-08-22 用 `s3.copy()` 將 `daily/2026-08-01.dump.age`（7.00 GB）
  複製到 `monthly/2026-08-01.dump.age` 成功，目的端大小與來源一致，無殘留 multipart。
  同批 3 份小於 5 GiB 的物件也正常。
- 現行促級段無任何錯誤處理：失敗會讓**已經上傳成功**的當日備份任務拋錯，
  進而觸發 Celery retry → 重跑整個 pg_dump → 再上傳一份 7 GB
- 促級失敗不影響 RPO（daily 仍在），因此告警即可

**附帶觀察**：實測時因連線中斷而留下孤兒 multipart，再次佐證中斷會留殘件，
`abort_stale_multipart_uploads()` 有其必要。

### Decision 5: 用量守門的門檻

**選擇**：備份後統計 `daily/` + `weekly/` + `monthly/` 的物件數與總 bytes：
- 物件數 > 30（23 的寬鬆上限）→ 告警
- 總容量 > **300 GB** → 告警

**Why**：
- 現行唯一的守門是 size anomaly 的日對日比值（0.5×–2.0×），對「每天多留一份」這種
  每日增幅不到 1% 的累積型故障**完全無效**——這就是它 3.5 個月沒響的原因
- 物件數是最直接的保留策略健康指標：穩態就該是 23 以內，> 30 必然代表沒刪乾淨
- 容量門檻由原訂 200 GB 上調為 300 GB：以實測 7.07 GB／份計，
  穩態 23 份 ≈ 163 GB，200 GB 只剩 37 GB 餘裕，而 dump 三個月成長 47%，
  約半年內就會自然撞線造成誤報。300 GB 對應約 42 份，仍遠低於本次事故的 108 份，
  偵測能力沒有實質損失。
- 物件數門檻不隨 dump 大小飄移，是這兩個門檻中較可靠的那一個；
  容量門檻的角色是抓「物件數正常但單份異常膨脹」的情形。

### Decision 6: 修正 Celery visibility_timeout（本次新增——重複執行的根因）

**選擇**：`celery_app.py` 的 `broker_transport_options` 增加 `"visibility_timeout": 14400`（4 小時）。

**Why**：
- `celery_app.conf` 設 `task_acks_late=True`（任務完成才 ack），但
  `broker_transport_options` 只設了 `priority_steps`，未設 `visibility_timeout`。
  worker 容器內實測 `kombu.transport.redis.Channel.visibility_timeout = 3600`
  （kombu 5.6.2 / celery 5.4.0）。
- 2026-08-21 備份實測 `duration_ms = 7,656,611`（2 小時 7 分，03:00 起跑 05:07 完成），
  **超過 3600 秒 → 任務未 ack 被 Redis 重新投遞**。
- 佐證：2026-08-22 清理時 abort 的 4 件 multipart 殘件，時間戳為
  8/17 的 04:00:39 與 05:00:52、8/20 的 03:00:08 與 04:00:11，**間隔正好整點 1 小時**，
  而 beat 只排 03:00 一次。即每天實際起跑 3 次。
- 後果：三個 pg_dump 並行打 prod DB、各自上傳 7.5 GB 覆寫同一 key、
  未完成者留下 multipart 殘件。**殘件的成因是重投，不是原先假設的 SIGKILL／redeploy。**
- 4 小時的取值：涵蓋目前 2 小時餘的執行時間並留一倍餘裕，
  同時不至於讓真正的 worker 死亡拖太久才被發現。

**副作用與緩解**：worker 真的死亡時，未 ack 的任務要等 4 小時（而非 1 小時）才被重投。
`cron_tick` 既有的 `stale_marked` / `orphans_reverted` 機制已在補這層，
且對備份而言重投延遲無實質影響（隔日仍有新的一份）。

**範圍聲明**：此設定作用於 broker 層，效果及於所有 queue 的所有 task。
本 change 只承諾修好備份任務的重投；`transcribe` 等長任務過去是否已受影響
需另行盤查，列為 follow-up。

## Risks / Trade-offs

- **app 端清掃刪錯檔案** → 這是唯一有資料風險的部分。緩解共四層：
  1. 只刪 key 完全符合 `<prefix>/YYYY-MM-DD.dump.age` 格式者
  2. 任一 prefix 若列舉結果少於保留份數則整個 prefix 跳過不刪
  3. **單次刪除上限保險閥**：一次清掃的刪除數超過 `_MAX_SWEEP_DELETES`（20）時，
     不執行刪除、改發告警要求人工介入。防止「首次執行或異常狀態下無人確認的大量刪除」
  4. 刪除前後的物件清單寫入 log
- **`delete_objects` 的部分失敗被忽略** → 該 API **回傳 `Errors` 陣列而不拋例外**，
  逐 key 的 AccessDenied 若不檢查就會靜默留下未刪物件，重演本次的失效模式。
  緩解：清掃必須檢查回傳的 `Deleted`／`Errors`，`Errors` 非空即視為清掃失敗並告警。
- **告警疲勞** → lifecycle 驗證改為狀態轉換才告警（Decision 2）；用量告警每日最多一封。
- **權限不足導致清掃也失敗** → 清掃結果會告警，屆時會明確指向 token 權限。
  但 `DeleteObject` 屬 Object 層權限，與已知失效的 bucket 層權限不同，預期可用。

## Migration Plan

1. 施工並部署本 change
2. 部署後檢查隔日一次備份的 log／告警：
   - 任務只執行一次（不再有整點 1 小時後的第二次 received）
   - 清掃有動作、`Errors` 為空
   - 用量在門檻內
   - lifecycle 驗證預期為 AccessDenied，且**只在首次狀態轉換時**發一封告警
3. 存量清除已於 2026-08-22 完成（見附錄），本次不需再執行

## Open Questions

- `transcribe` 等長任務過去是否也曾因 visibility_timeout 而重複執行——需盤查 DB 與計費紀錄（follow-up）
- R2 API token 是否要升級為 Admin Read & Write 以恢復 lifecycle 這層防護（部署後可選）

---

## 附錄：既有存量的一次性清除（**2026-08-22 已執行完畢**）

| | 清理前 | 清理後 |
|---|---|---|
| 物件 | 108 份 | 12 份 |
| 容量 | 472.80 GB | 64.01 GB |
| multipart 殘件 | 4 件 | 0 件 |

保留內容（方案 B）：daily 最新 7 份（08-15~08-21）＋ `weekly/2026-05-10`
＋ 4 個補位月錨 `daily/2026-05-07`、`06-01`、`07-01`、`08-01`。
其後 4 個月錨已用 managed copy 促級到 `monthly/` 前綴
（因為清掃只保留 `daily/` 最新 7 份，月錨留在 daily/ 會被掃掉）。
現況：daily 11 + weekly 1 + monthly 4 = 16 份，約 77.8 GB。
清掃上線後預期收斂為 daily 7 + weekly 1 + monthly 4 = 12 份。

**執行方式**（與原附錄設想的本機 aws cli + Keychain 不同——Keychain 那四筆至今仍是佔位符）：

```bash
# 憑證不出容器：直接在 worker 容器內用容器自己的 R2_BACKUP_* env 跑 boto3
zeabur service exec --id <worker-service-id> -i=false -- \
  sh -c "echo <base64-encoded-python> | base64 -d > /tmp/x.py && python -u /tmp/x.py"
```

長時間操作（例如 >5 GiB 的 managed copy）須在容器內以 `nohup ... &` 背景執行並輪詢 log，
否則 `zeabur service exec` 逾時（524）斷線會殺掉行程並留下孤兒 multipart（實地踩過一次）。

**硬性要求**（未來若需再次人工清除）：
- 刪除前必須留存完整物件清單作為證據
- 刪除前必須逐一驗證保留清單中的物件存在且檔頭為合法 age 加密檔
- 最新的 monthly 與最新的 daily **絕不可刪**
- 這是唯一的離站備份，任何刪除都需人工逐項確認後才執行

證據與清單留存於 `docs/case-studies/r2-cleanup-2026-08-22/`（依專案規則不進 git）。
