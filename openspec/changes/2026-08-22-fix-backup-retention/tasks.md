# Tasks

## 1. `celery_app.py`：消滅任務重投（根因）

- [x] 1.1 `broker_transport_options` 增加 `"visibility_timeout": 14400`，
      並在該處註解記錄理由：`task_acks_late=True` + kombu 預設 3600s，
      2026-08-21 備份實測 `duration_ms=7,656,611`（2h07m）導致當天重投 3 次
- [x] 1.2 `backend/tests/test_celery_routing.py` 新增 `test_broker_visibility_timeout_covers_long_tasks`：
      斷言 `celery_app.conf.broker_transport_options["visibility_timeout"] == 14400`，
      且該值大於實測的備份耗時 7656 秒

## 2. `r2_backup_client.py`：lifecycle 規則與驗證

- [x] 2.1 `_LIFECYCLE_RULES` 增加第 4 條 `AbortIncompleteMultipartUpload`（`DaysAfterInitiation: 1`），
      並抽出 `_EXPECTED_RULE_IDS` 常數供驗證比對；同時修正該常數上方註解——
      現行註解宣稱 "the app does not need to walk and delete artifacts"，與本 change 相反
- [x] 2.2 新增 `verify_lifecycle_policy(client, bucket) -> tuple[bool, list[str]]`：
      呼叫 `get_bucket_lifecycle_configuration`，回傳 (是否涵蓋全部預期 rule ID, 實際 rule ID 清單)；
      `ClientError`／`BotoCoreError` 由 caller 處理，本函式不吞例外
- [x] 2.3 新增 `read_verify_state(client, bucket) -> str | None` 與
      `write_verify_state(client, bucket, outcome)`：以 R2 key `_state/lifecycle_verify.json`
      持久化上次驗證結果（`"ok"` / `"failed"`）。讀取時 404 回 `None`；
      不可依賴 worker 記憶體（容器隨時可能重啟）
- [x] 2.4 `apply_lifecycle_policy()` 保持只負責寫入，不吞例外（讓 caller 決定告警）

## 3. `r2_backup_client.py`：保留清掃與用量統計

- [x] 3.1 新增 `_KEY_RE`（`^(daily|weekly|monthly)/(\d{4}-\d{2}-\d{2})\.dump\.age$`）與解析 helper；
      新增 `_RETENTION = {"daily": 7, "weekly": 4, "monthly": 12}` 與 `_MAX_SWEEP_DELETES = 20`
- [x] 3.2 新增 `sweep_retention(client, bucket) -> dict`：
      逐 prefix 列舉（處理分頁）→ 過濾不符 `_KEY_RE` 的 key（warning log，永不刪，
      `_state/lifecycle_verify.json` 因此自動被排除）→ 依日期降序 → 保留 7/4/12；
      **任一 prefix 物件數 ≤ 保留份數則整個 prefix 跳過**；
      回傳每 prefix 的 retained/deleted 計數、刪除 key 清單、`needs_review` 旗標與 `errors` 清單
- [x] 3.3 `sweep_retention` 保險閥：跨 prefix 合計刪除數 > `_MAX_SWEEP_DELETES` 時，
      **不執行任何刪除**，回傳 `needs_review=True` 與待刪清單供 caller 告警
- [x] 3.4 `sweep_retention` 檢查 `delete_objects` 回傳值：該 API 回傳 `Errors` 陣列**而不拋例外**，
      必須把非空 `Errors`（key + error code）收進回傳的 `errors` 清單，caller 據此視為清掃失敗
- [x] 3.5 新增 `abort_stale_multipart_uploads(client, bucket, older_than_hours=24) -> int`：
      `list_multipart_uploads` 分頁 → 依 `Initiated` 過濾 → `abort_multipart_upload`；無 `Uploads` 時 no-op
- [x] 3.6 新增 `bucket_usage(client, bucket) -> dict`：回傳各 prefix 物件數、總物件數、總 bytes

## 4. `db_backup.py`：串接與告警

- [x] 4.1 lifecycle 段改為：apply → verify → 讀取 `_state` 前次結果 → **僅在狀態轉換時**告警。
      `failed`→`ok` 發 `[PodcastRAG] DB backup lifecycle policy restored`；
      `ok`／無狀態→`failed` 發 `[PodcastRAG] DB backup lifecycle policy NOT applied`（含 expected vs actual 與 error code）；
      `failed`→`failed` 只記 warning log 不發信。**備份流程一律不中斷**
- [x] 4.2 促級段改用 managed copy（`client.copy()`，內部自動走 multipart copy），
      整段包 try/except，失敗發 `[PodcastRAG] DB backup promotion failed YYYY-MM-DD` 並**不拋錯**，
      回傳值記 `promotion_ok`
- [x] 4.3 備份成功後依序呼叫 `sweep_retention()` → `abort_stale_multipart_uploads()`。
      `needs_review=True` 時發 `[PodcastRAG] DB backup retention sweep needs review`；
      `errors` 非空或任一步拋 `ClientError`／`BotoCoreError` 時發
      `[PodcastRAG] DB backup retention sweep failed YYYY-MM-DD`。兩者皆**不拋錯**
- [x] 4.4 呼叫 `bucket_usage()`，物件數 > 30 或總量 > 300 GB 即發
      `[PodcastRAG] DB backup bucket usage alert`；本檢查全程 advisory，
      任何例外只記 warning log，回傳值以 `object_count: None` / `total_bytes: None` 表示未取得
- [x] 4.5 task 回傳值增加 `swept`／`aborted_uploads`／`object_count`／`total_bytes`／`promotion_ok` 欄位
      （base spec 原本 pin 了 `{"sent_count", "size_bytes", "duration_ms"}`，delta spec 已同步修改）

## 5. 測試

- [x] 5.1 `test_r2_backup_client.py`：lifecycle 規則含 4 條且 ID 正確；
      `verify_lifecycle_policy` 在缺規則／完整兩種情況的回傳；重複套用同一組規則不改變送出的 payload（冪等）
- [x] 5.2 `test_r2_backup_client.py`：`read_verify_state` 在 404 時回 `None`、
      在既有物件時回 `"ok"`／`"failed"`；`write_verify_state` 寫入的 key 為 `_state/lifecycle_verify.json`
- [x] 5.3 `test_r2_backup_client.py`：`sweep_retention` — 超量刪除、剛好不刪、不足份數跳過、
      不符格式的 key（含 `_state/lifecycle_verify.json`）不被刪、分頁列舉
- [x] 5.4 `test_r2_backup_client.py`：`sweep_retention` 保險閥 — 待刪 21 件時不刪任何東西且回 `needs_review=True`；
      待刪 20 件時正常刪除
- [x] 5.5 `test_r2_backup_client.py`：`sweep_retention` 在 `delete_objects` 回傳非空 `Errors`
      （未拋例外）時，把失敗 key 收進 `errors` 清單
- [x] 5.6 `test_r2_backup_client.py`：`abort_stale_multipart_uploads` — 逾時 abort、未逾時保留、空清單 no-op
- [x] 5.7 `test_r2_backup_client.py`：`bucket_usage` 計數與加總
- [x] 5.8 `test_db_backup.py`：lifecycle 驗證失敗且前次為 `ok`／無狀態→發告警且備份仍完成
- [x] 5.9 `test_db_backup.py`：lifecycle 連續兩次 `failed`→第二次不發信、只記 log
- [x] 5.10 `test_db_backup.py`：lifecycle 由 `failed` 轉 `ok`→發 restored 告警
- [x] 5.11 `test_db_backup.py`：促級拋錯→發告警、任務不拋錯、`pg_dump` 不被重跑、`promotion_ok=False`
- [x] 5.12 `test_db_backup.py`：清掃拋錯→發 sweep failed 告警、任務不拋錯；
      `needs_review=True`→發 needs review 告警且未刪除
- [x] 5.13 `test_db_backup.py`：物件數 31／總量 301 GB 各自觸發用量告警；23 物件 163 GB 不觸發；
      `bucket_usage` 拋錯時任務仍成功且回傳 `object_count=None`

## 6. 文件

- [x] 6.1 `docs/disaster-recovery.md` 增加「如何確認保留策略生效」一節：
      查 lifecycle、查物件數、查 multipart 殘留的具體指令，
      採 `zeabur service exec` 在 worker 容器內跑 boto3 的路線（本機 Keychain 憑證仍是佔位符）
- [x] 6.2 `docs/disaster-recovery.md` 增加人工清掃步驟與硬性要求：
      刪前留存清單、刪前驗證保留檔的 age 檔頭、最新 monthly／daily 絕不可刪、
      長時間操作須在容器內 `nohup` 背景執行（exec 逾時會斷線殺行程並留孤兒 multipart）

## 7. 部署與驗收

- [ ] 7.1 部署後檢查隔日備份的 worker log：`Task ... received` 只出現一次
      （不再有整點 1 小時後的第二次），確認重投已消除
- [ ] 7.2 檢查同一次備份的 log／告警：清掃有動作且 `errors` 為空、用量在門檻內、
      lifecycle 驗證預期為 AccessDenied 且只在首次狀態轉換發一封告警
- [ ] 7.3 確認物件數收斂到 daily 7 + weekly 1 + monthly 4 = 12 份、容量約 78 GB
      （既有存量已於 2026-08-22 清除完畢，本次不需再執行清除）
- [ ] 7.4 若 7.2 出現 `lifecycle policy NOT applied` 告警，評估是否到 Cloudflare dashboard
      將 R2 API token 由 Object Read & Write 升級為 Admin Read & Write（可選，非阻塞）
