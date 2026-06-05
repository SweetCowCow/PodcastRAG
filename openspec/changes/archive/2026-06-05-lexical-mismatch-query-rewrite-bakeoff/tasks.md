## 1. Arm 集固定為 control、query-expansion、hyde、multi-vector

- [x] 1.1 實作 spec requirement「Bake-off compares a fixed set of query-rewrite arms」：新增 admin endpoint `POST /admin/diagnose/lexical-bakeoff` + backend service 層 arm 統一介面（輸入 `(question, db, embed_step)` → 輸出 `(lexical_question, embedding_vectors, extra_llm_calls)`），endpoint 對每 item 依 arm 跑「改寫 → embed → `rag.retrieve_hybrid` → 比對 GT 得 prefilter-rank」，四 arm 共用同一條 `retrieve_hybrid` 與候選池設定。驗證：以 control arm 對單一案例打 endpoint 跑通，取回標靶 chunk 的 prefilter-rank 數字。
- [x] 1.2 在 backend service 層實作 `control` arm（原 question 直送，行為等價既有 prefilter-rank endpoint，退步偵測基準）。驗證：control 對 b20 的 prefilter-rank 與 EQ3a 診斷一致（@1719≈78）。
- [x] 1.3 在 backend service 層實作 `query-expansion` arm（LLM 同義/相關詞擴充 → 併入 `lexical_question`、保留原 embedding；prompt 固定、temperature=0、記錄 model 與改寫結果於 `rewrite_debug`）。驗證：對 b20 輸出擴充後 lexical query 並落結果 JSON。
- [x] 1.4 在 backend service 層實作 `hyde` arm（LLM 生成假設答案文本 → `embed_texts` 取向量當 `embedding_vectors`、原 question 保留 lexical；prompt 固定、temperature=0、記錄 model 與 HyDE 文本）。驗證：對 b20 產出 HyDE 文本與 embedding，retrieve 跑通。
- [x] 1.5 在 backend service 層實作 `multi-vector` arm（LLM 拆原 query 為 2–3 子查詢各 `embed_texts`，對候選 chunk 取 max-sim 聚合；拆法與聚合記入 `rewrite_debug`）。驗證：對 b20 產出多子查詢與聚合分數，retrieve 跑通。

## 2. 測試案例固定為 b20 + b23 + calibration 防退步集

- [x] 2.1 實作 spec requirement「Fixed test cases with calibration regression guard」：從 `extended-multi-turn-40.json` 載 b20（must @1719/@1993）、b23（must @1766/@1819/@1847/@1866）+ calibration 防退步集（沿用 calibration_8）。驗證：印出三組 query 與 must chunk id，數量與 GT 一致。
- [x] 2.2 實作 calibration 退步偵測：對 control 原本召得回的 query，若某非 control arm 召不回 must 則標該 arm regressing。驗證：建構一個 control 命中、arm 失手的案例，確認標記為退步。

## 3. 主 metric = 標靶 chunk prefilter-rank，副 metric = chunk_recall@must，並列成本欄

- [x] 3.1 實作 spec requirement「Metrics are prefilter-rank, chunk_recall@must, and cost」，落實 design 決策「主 metric = 標靶 chunk prefilter-rank，副 metric = chunk_recall@must，並列成本欄」：每個 (arm, case) cell 記錄標靶 prefilter-rank（主）、chunk_recall@must（副）、額外 LLM call 數與平均延遲。驗證：結果 JSON 每 cell 四個 metric 群齊全、無缺欄。
- [x] 3.2 實作 cell 級錯誤隔離：單一 (arm, case) 拋錯時該 cell 標 `ERROR` 並續跑其餘 cell。驗證：人為讓一 arm 拋錯，其餘 cell 仍完成且報告含 ERROR cell。

## 4. 新增 admin bake-off endpoint，arm 改寫在 backend service，harness 走 HTTP orchestrate

- [x] 4.1 實作 spec requirement「Bake-off runs offline and read-only」：新增的 `/admin/diagnose/lexical-bakeoff` endpoint 內部 `retrieve_hybrid` 唯讀（不寫表）、不走線上 `/shows/{id}/query`、不改既有 prefilter-rank 行為；harness 復用 `audit_voyage_pipeline.py` 的 prod session 樣板走 HTTP orchestrate。驗證：跑一輪確認無任何寫入、retrieve 結果來自新 endpoint。
- [x] 4.2 實作 runner CLI（arm 子集 / case 子集 / 目標 backend 參數）；目標為 prod 時開跑前 curl `/me` 驗 200，失敗則 fail loud 中止、不產半套報告（依 reference_prod_eval_session）。驗證：用過期 session 跑 prod，確認中止且無 results 檔。

## 5. 評分視角 = mixed（量化 metric 判 arm 優劣，human 視角判落地）與報告產出

- [x] 5.1 實作 spec requirement「Report contract」，落實 design 決策「評分視角 = mixed（量化 metric 判 arm 優劣，human 視角判落地）」：產出機器可讀 JSON（落 `backend/scripts/lexical_bakeoff/results/`）與人讀 markdown 報告（落 `docs/case-studies/`），含完整 arm × case 矩陣（無 placeholder）、評分視角段落（量化 arm 排名 vs human 落地判斷）、小樣本限制聲明。驗證：矩陣 cell 數 = arm 數 × case 數，三段落齊備。
- [x] 5.2 對 prod 跑完整 bake-off：先取 control 基準線再於報告中定錨勝者門檻（prefilter-rank/chunk_recall 硬數字不預設、依 control 定錨）；產勝者判定（附量化依據）+ 每個非 control arm 的 calibration 退步結論。驗證：報告含勝者 + 量化依據 + 每 arm calibration 退步/未退步結論。

## 6. stop-the-line：勝者不自動落地，等 Jacky 拍板

- [x] 6.1 實作 spec requirement「Stop-the-line before landing a winner」：報告明記「勝者為待人工核准之建議，prod retrieve path 未變更」，流程停下等 Jacky 拍板是否落地、由哪條後續 change 落地。驗證：報告含 stop-the-line 段、git 確認無 prod retrieve path 程式碼被改。
