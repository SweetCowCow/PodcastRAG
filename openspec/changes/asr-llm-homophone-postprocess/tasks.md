## 1. 資料模型與 migration

- [x] 1.1 在 `backend/app/models/asr_correction_term.py` 為 `asr_correction_terms` 加 `source`（text，`manual`/`llm`，default `manual`）與 `status`（text，`pending`/`approved`/`rejected`，default `approved`）欄位，並新增 alembic migration；migration 對既有列回填 `source='manual'`、`status='approved'`，達成 **ASR correction rule data model**（modified）。驗證：本機 Postgres `alembic upgrade head` 與 downgrade 皆通過；既有 6 條規則升級後皆為 `manual`/`approved`/`enabled=true`，行為與 EQ2a 不變。

## 2. 規則解析改核准制

- [x] 2.1 修改 `backend/app/services/asr_correction.py` 的 `load_rules`，達成 **Rule scope resolution by show**（modified）：只回 `status='approved' AND enabled=true` 的 global∪show 規則，排除 pending/rejected/disabled。驗證：unit test 驗 pending 候選不被解析、approved+enabled 的 global 與 show 規則被 union、rejected 被排除。

## 3. LLM 同音字偵測 service

- [x] 3.1 新增 `backend/app/services/asr_homophone.py` 的偵測函式，達成 **LLM homophone detection produces word-level pairs** 與 **Detection uses centralized AI step configuration**：吃整集逐字稿、用 `get_step_config(session, 'asr_homophone')` 取 model/prompt 呼叫 LLM、解析回傳為 `[{wrong, correct}]` 詞級 pair；解析須先 strip markdown code block 再 `json.loads`（AI Hub 不保證 json_object）。驗證：unit test 以 mock LLM 回傳含 code block 的 JSON，驗正確解析出 pair list；無同音字時回空 list。
- [x] 3.2 在同檔實作 **Detection is fail-open**：LLM 呼叫或解析拋例外時 log warning 並回空 pair list。驗證：unit test 模擬 LLM 例外，驗回空 list 且不向外拋。
- [x] 3.3 在同檔實作候選持久化，達成 **Detected pairs persisted as pending candidates** 與 **Duplicate detection skipped**：對每個 pair 以 `source='llm'`、`status='pending'`、`enabled=false`、`scope='show'`+episode 的 show_id 寫入；寫入前查同 `(wrong, scope, show_id)` 任何 status 已存在則跳過、不覆寫。驗證：integration test（真實 Postgres）驗新 pair 寫成 pending 候選、重複 pair（已 approved 或已 rejected）被跳過且既有 status 不變。

## 4. AI step 註冊

- [x] 4.1 在 AI step 設定（`backend/app/services/ai_step_resolver.py` 及其 seed/設定來源）註冊 `asr_homophone` step 與預設 prompt（約束：只回同音誤聽詞級 pair、保留專名拼寫意圖、不確定不回、輸出嚴格 JSON 陣列），達成 **asr_homophone AI step is configurable**。驗證：`get_step_config(session, 'asr_homophone')` 回有效 model+prompt；admin AI step 設定列表含該 step。

## 5. 轉錄管線接入

- [x] 5.1 在 `backend/app/workers/tasks.py` 的 `_run` 接入第一層偵測，達成 **LLM homophone detection precedes dictionary correction** 與 **Detected pairs applied to the current episode immediately**：取得 Whisper result 後、寫 segment 前，先跑 `asr_homophone` 偵測 → 用 `apply_corrections` 把 LLM pair 套到本集 segment（不查 DB、不卡核准）→ 再套第二層已核准字典規則 → 才 `build_chunks`/embedding；偵測層 fail-open。驗證：integration test 轉錄一集，LLM mock 回一組 pair，驗 segment/`content`/chunk 同時反映 LLM 校正與字典校正；模擬偵測失敗時轉錄仍以字典完成。

## 6. dry-run 成本估算

- [x] 6.1 實作 **Detection cost dry-run estimation**：給定 pilot episode 集合，估算偵測的 token 用量與成本（參考逐字稿長度 + step model 計價），不呼叫 LLM、不寫候選、不改 transcript。驗證：test 驗 dry-run 回 token/成本估值且無任何 DB 寫入或 LLM 呼叫。

## 7. 候選審核 API

- [x] 7.1 在 `backend/app/api/admin/asr_corrections.py` 新增候選審核端點，達成 **Candidate review API**：list 支援 `source`/`status` 過濾；approve 設 `status='approved'`+`enabled=true`；reject 設 `status='rejected'`+`enabled=false`；全 admin-only。驗證：API test 驗 list 過濾 pending+llm、approve 後該規則進 `load_rules` 解析、reject 後不被解析、非 admin 被拒。

## 8. 後台候選審核 UI

- [ ] 8.1 在 `src/AdminAsrCorrectionTab.jsx` 新增「待審核候選」區，達成 **Pending candidate review section**：列出 `source='llm'`+`status='pending'` 候選（wrong/correct/所屬 show）+ 核准/駁回按鈕，雙語、用 TOKEN 設計系統，操作後列表更新。驗證：browser smoke 候選列表載入 + 核准一筆後該筆離開待審區並成為生效規則。

## 9. 測試與 pilot 驗證

- [x] 9.1 後端測試全綠（unit + integration，真實 Postgres 跑 detection service / load_rules / 候選持久化 / 審核 API）。驗證：對應 pytest 全數通過。
- [ ] 9.2 部署 migration + backend/worker/dispatcher/beat + 前端（同 EQ2a 模式），於後台設定 `asr_homophone` step model/prompt，並跑 pilot：先對「這又沒有很屌」3–5 集 dry-run 估成本 → 確認後對該批跑偵測 → 後台檢視 LLM 候選 → 對 EQ2a 已知 6 條錯字算 precision/recall（LLM 有無抓到已知、有無亂報）→ 核准正確候選。驗證：prod 偵測產出候選、precision/recall 數據記錄於對應 case study、核准後搜尋正字命中。
