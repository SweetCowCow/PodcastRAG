## 1. 後端：核准可帶 correct 覆寫（F3）

- [x] 1.1 在 `backend/app/schemas/asr_correction.py` 新增 approve 請求 schema（如 `AsrCandidateApprove`，欄位 `correct: str | None = None`，`max_length=200`），達成 **Candidate review API**（modified）。驗證：欄位可選、預設 None。
- [x] 1.2 在 `backend/app/api/admin/asr_corrections.py` 的 `approve_candidate` 改吃 optional body：有 `correct` 就覆寫 `row.correct` 再設 `status='approved'`+`enabled=true`；無則維持原值；不改 `wrong`/`scope`/`show_id`；保持 admin-only。驗證：API test 驗 (a) 不帶 correct → 原值 approved+enabled (b) 帶 correct → 覆寫值 approved+enabled (c) 非 admin 403。

## 2. 偵測解析容錯（F5）

- [x] 2.1 強化 `backend/app/services/asr_homophone.py` 的 `_parse_pairs`：在既有 strip code block + `pairs`/`corrections` 鍵之外，加 (a) 物件即單筆 `{wrong,correct}`、(b) 鍵名大小寫/空白變體正規化、(c) 回應夾雜非 JSON 文字時用正則擷取第一個 JSON 陣列或物件再 parse、(d) 全形引號轉半形。解析失敗仍回空（fail-open 不變）。不改 `detect_homophones` RAGEC 流程與 post-filter。驗證：unit test 對 5 種變體 payload（裸陣列／code block 包陣列／物件包 pairs／單筆物件／前後夾 prose）皆正確解析出 pair；壞 payload 回空。

## 3. 前端：核准可編輯 correct（F3）

- [x] 3.1 在 `src/AdminAsrCorrectionTab.jsx` 待審核候選區把 correct 改為可編輯輸入框（預填 LLM 偵測值，state 逐列管理），「核准」送出時帶當前 correct 值到 `POST /admin/asr-corrections/{id}/approve`；雙語、用 TOKEN 設計系統；操作後列表更新。達成 **Pending candidate review section**（modified）。驗證：browser smoke 改一筆候選 correct 後核准 → 生效規則為編輯後的值、該筆離開待審區。

## 4. 測試與部署

- [x] 4.1 後端測試全綠：approve-with-correct（含不帶/帶/非 admin 三案）+ `_parse_pairs` 5 變體 + 既有 EQ2b 測試不退步。驗證：對應 pytest 全數通過。
- [x] 4.2 部署 backend + 前端（同 EQ2a/EQ2b 模式），prod browser smoke：核准可編輯一筆生效；並用一個 AI Hub 非 OpenAI 模型（如 qwen-3-235b）對 pilot 集跑 `homophone_pilot --run` 驗證解析容錯後不再回 0。驗證：prod 核准編輯生效 + 該模型能解析出 pair。
