## 1. 設定旗標

> 對應 spec requirement「Conditional HyDE activation is gated by a default-off flag」；design 決策「設定旗標（保留既有、新增條件式）」。

- [x] 1.1 在 `backend/app/core/config.py` 的 `Settings` 新增 `hyde_conditional_activation: bool = False`、`hyde_mismatch_overlap_threshold: float`（先設暫定值如 0.3，task 5.2 校準後回填）、`hyde_mismatch_topn: int = 5`。實作 spec requirement「Conditional HyDE activation is gated by a default-off flag」。驗證：import settings 不報錯、三個欄位可由環境變數覆蓋（單元測試讀預設值通過）。

## 2. 失配偵測訊號（主案 b）

> 對應 design 決策「失配偵測訊號 = query↔base 召回 top-k 詞面重疊度（主案 b）」。

- [x] 2.1 在 `backend/app/services/hyde_retrieval.py` 新增純函式 `lexical_overlap_ratio(question: str, hits: list[RetrievedChunk]) -> float`：用專案既有中文 tokenizer（與 lexical ts_query 建構同一套）對 question 斷詞，計算 question token 集合中出現在 hits 文本聯集裡的比例，回傳 [0,1]。驗證：單元測試——query 詞全在 top-k 文本回傳接近 1.0、全不在回傳接近 0.0、空 hits 回傳 0.0 不除零。

## 3. 兩階段召回 orchestrator

> 對應 spec requirement「Two-stage retrieval activates HyDE only on detected lexical mismatch」與「Conditional activation fails open to the base retrieval result」；design 決策「兩階段召回流程（條件式啟用時）」。

- [x] 3.1 在 `hyde_retrieval.py` 擴充 `HydeResult` 新增 `conditional_mode: bool`、`overlap_ratio: float | None`、`triggered_by_mismatch: bool`（皆給預設值，不破壞既有建構點）。驗證：既有 `resolve_semantic_embedding` 回傳路徑補上預設值後單元測試通過。
- [x] 3.2 在 `hyde_retrieval.py` 新增兩階段 orchestrator（如 `resolve_chunk_hits_conditional()`），封裝：base 召回 → 量 overlap → 達標回 base hits（used_hyde=False、零額外成本）/ 未達標生 HyDE 並第二輪召回回新 hits。複用既有 HyDE 生成+embed 邏輯。任何失敗 fail-open 回 base hits、記 warning、不 raise。實作 spec requirement「Two-stage retrieval activates HyDE only on detected lexical mismatch」與「Conditional activation fails open to the base retrieval result」。驗證：單元測試覆蓋高重疊不開、低重疊開第二輪、HyDE 生成失敗 fail-open 回 base hits 四情境。

## 4. 接上 retrieve 進入點

- [x] 4.1 將 `backend/app/api/query.py` 三處 retrieve 進入點（`public_search_show` ~L211、`query_show` search 模式 ~L453、chat rule-based path ~L540）改為：兩 flag 全開時走 task 3.2 orchestrator；否則維持現況呼叫 `resolve_semantic_embedding` + `retrieve_hybrid`。`route_episodes` 與 lexical question 維持原問題不變。驗證：單元/整合測試——master off 不進 HyDE、master on+conditional off 維持無差別 HyDE（既有行為不回歸）、兩開且低重疊走兩階段。

## 5. 門檻校準

> 對應 design 決策「門檻校準（用既有 harness）」。

- [x] 5.1 新增 `backend/scripts/hyde_ab/calibrate_threshold.py`：對 10 標靶 + 8 calibration 兩組各題量 overlap ratio，在候選 cutoff（0.1/0.2/0.3/0.4/0.5）下輸出每 cutoff 的標靶啟用率、calibration 誤啟用率、預期 must-rank gain 表。複用既有 `backend/scripts/hyde_ab/run.py` harness 與 prod eval session。驗證：腳本對兩組各題印出 overlap + 各 cutoff 統計表，可實際執行不報錯。
- [ ] 5.2 跑 5.1 校準腳本對 prod，選出能把兩組分開的 cutoff（標靶多數 < cutoff、calibration 多數 >= cutoff），把結果與選定 cutoff 寫入 `docs/case-studies/hyde-conditional-activation-calibration.md`（不進 git commit），並把選定值回填 task 1.1 的 `hyde_mismatch_overlap_threshold` 預設與 `hyde-retrieval` spec。驗證：case study 列每題 overlap + 選定 cutoff 理由；config 預設值已更新。

## 6. 觀測接線

> 對應 spec requirement「Conditional activation exposes mismatch observability fields」；design 決策「觀測欄位」。

- [ ] 6.1 在 `backend/app/api/admin/diagnose_prefilter.py` 的 `/admin/diagnose/prefilter-rank` 回傳擴充 `conditional_mode` / `overlap_ratio` / `triggered_by_mismatch` 欄位。實作 spec requirement「Conditional activation exposes mismatch observability fields」。驗證：對 prod 打一筆條件式啟用查詢，回應 JSON 含三欄位且值合理（失配題 triggered_by_mismatch=true）。

## 7. 驗證收尾

- [ ] 7.1 跑 backend 既有測試套件確認無回歸，並對 prod（flag 維持 off）做一筆 smoke 確認 retrieve path 正常、未受影響。驗證：測試全綠；prod smoke 回 200 且 used_hyde=False。
