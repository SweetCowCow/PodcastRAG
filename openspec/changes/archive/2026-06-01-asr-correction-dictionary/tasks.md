## 1. 資料模型與 migration

- [x] 1.1 建立 `asr_correction_terms` 表的 SQLAlchemy model 與 alembic migration，達成 **ASR correction rule data model**（欄位 wrong/correct/scope/show_id/enabled/note/稽核欄位 + 唯一約束 `(wrong, scope, show_id)`），採設計決策「獨立 asr_correction_terms 表與 tokenizer 字典區隔」。驗證：本機 Postgres 跑 `alembic upgrade head` 與 downgrade 皆通過，model 欄位與約束與 spec 對齊。

## 2. 校正套用 service

- [x] 2.1 實作 `backend/app/services/asr_correction.py` 的 `apply_corrections(text, rules)`，達成 **Literal whole-term matching**（`wrong` 以 literal 完整字串比對、regex metacharacter 視為字面），落實設計決策「整詞精確 literal 比對與誤傷防護」。驗證：unit test 涵蓋 literal 替換、`a.b` 點號字面不當萬用字元、spec Example 表三案例。
- [x] 2.2 實作同檔的 `load_rules(session, show_id)`，達成 **Rule scope resolution by show**（回傳 enabled 的 global ∪ 該 show 規則、排除 disabled），落實設計決策「適用範圍 global 與 show-scoped 的 union 載入」。驗證：unit test 驗 G/H 命中、K（他 show）不命中、disabled 規則被排除。

## 3. 新轉錄鏈式套用

- [x] 3.1 在 transcribe worker 的 `_run`（`backend/app/workers/tasks.py`）接入 **ASR correction applied before chunking**：取得 Whisper result 後、寫入 segment 與 `transcript.content` 及 `build_chunks` 之前套校正，落實設計決策「校正在 chunking 前於源頭一次套用」與「新轉錄鏈式套用點與 fail-open」（校正失敗 log warning 不擋轉錄）。驗證：integration test（真實 Postgres）轉錄一集後 segment text / content / chunk 皆為正字；模擬校正載入失敗時轉錄仍完成。

## 4. 批次回填

- [x] 4.1 實作受影響 chunk 重算邏輯，達成 **Backfill recomputes only affected chunks**（更新含 `wrong` 的 segment text → 經 `segment_ids` 反查受影響 chunk → 重組 text、重算 `embedding`/`embedding_v2`/`text_tsvector`，未受影響 chunk 不動），落實設計決策「批次回填只重算受影響的 chunk」。驗證：integration test 驗 C1 四欄重算、C2 不變、校正詞 keyword search 可命中既有 chunk。
- [x] 4.2 將回填包成 Celery 任務，達成 **Backfill runs as a resumable idempotent background task**（分批 commit、idempotent、單 chunk 失敗隔離並回報受影響 segment/chunk 計數與失敗清單），落實設計決策「批次回填用可續跑的 Celery 背景任務」。驗證：test 驗單 chunk embedding 失敗被隔離不中斷整批、同規則二次執行不重複套用。

## 5. Admin API

- [x] 5.1 實作 `backend/app/api/admin/asr_corrections.py` 達成 **Correction rule CRUD API**（list / create / update 含 toggle enabled / delete / backfill；backfill 支援 `dry_run`：`dry_run=true` 只回報「將重算 N 個 chunk + 預估成本」不執行、`dry_run=false` enqueue 背景任務回 task 識別；`scope='show'` 缺 `show_id` 回 HTTP 422；全 endpoint admin-only），並註冊進 `backend/app/api/admin/__init__.py`。驗證：API test 驗 CRUD、422、非 admin 被拒、dry_run 回預估不執行、backfill 回 task 識別。

## 6. Admin 前端 tab

- [x] 6.1 實作 `src/AdminAsrCorrectionTab.jsx` 達成 **Admin tab manages correction rules**（列表 / 新增 / 編輯 / 啟用停用 / 刪除、雙語、TOKEN 設計系統），並掛載至 `index.html`、`AdminPage.jsx` pages 物件與 `Shared.jsx` 後台 nav 入口。驗證：browser smoke 列表載入 + 新增一條 + toggle 生效。
- [x] 6.2 加入 **Match-count preview before save**（儲存前顯示 `wrong` 在 scope 內命中的 segment 數），呼應設計決策「整詞精確 literal 比對與誤傷防護」的誤傷防線。驗證：browser 輸入 `wrong` 與 scope 後顯示命中數。
- [x] 6.3 加入 **Trigger backfill with progress feedback**（觸發回填前先呼叫 `dry_run` 顯示「將重算 N 個 chunk + 預估成本」確認框、確認後才執行；再顯示進度與完成計數 + 標示「新增規則需手動回填既有逐字稿」）。驗證：browser 觸發回填先跳預估確認框、確認後顯示最終計數，提示文字存在。

## 7. 驗證與部署

- [x] 7.1 後端測試全綠（unit + integration，真實 Postgres 跑 service / 回填 / API 三層）。驗證：對應 pytest 全數通過。
- [x] 7.2 依設計 Migration Plan 部署 migration + backend/worker/dispatcher/beat 四服務 + 前端，並跑 prod smoke：新增一條已知錯字規則（例 咪有企→滅火器）→ 批次回填該 show → 搜尋正字命中既有內容。驗證：prod 搜尋正字命中、UI/console 無異常。
