# 實作任務

## 1. Schema 擴充 + validator 守門

- [x] 1.1 修改 `backend/eval/datasets/_schema.json`：在 `definitions.Item.properties` 加 `eval_mode` enum `["chunk_id", "open_set_lenient", "enumeration"]`；把 `eval_mode` 加到 `required` 陣列；保留 `expected_episode_ids` 既有定義
- [x] 1.2 在 `_schema.json` 用 `oneOf` / `allOf` 條件子句強制：(a) `eval_mode == "enumeration"` ⟹ `expected_episode_ids` 必填且 `minItems: 1`；(b) `eval_mode != "enumeration"` ⟹ `expected_episode_ids` 缺席或為空陣列；具體 JSON Schema draft-07 語法 apply 階段決定但需通過下方 1.4 的 validator 測試
- [x] 1.3 用 `jsonschema` Python package 寫驗證 helper（或擴充既有的）使 `python -m backend.eval.scripts.build_golden_set --validate` 或等效 CLI 跑得起來，輸出 missing/invalid `eval_mode` 與 enumeration constraint 違規
- [x] 1.4 加 unit test (`backend/eval/tests/test_schema.py` 或既有測試檔擴充)，覆蓋四個 case：缺 `eval_mode` 應 fail、`enumeration` + 空 `expected_episode_ids` 應 fail、`chunk_id` + 非空 `expected_episode_ids` 應 fail、合法三種 mode 應 pass

## 2. Migrate 既有 30 題加 eval_mode 欄位

- [x] 2.1 修改 `backend/eval/datasets/this-not-that-cool.json`：在 q01-q23 每題加 `eval_mode: "chunk_id"` 欄位（保持其餘欄位順序與內容不變）
- [x] 2.2 修改 `backend/eval/datasets/_pending_review.json`：q11-q23 補 `eval_mode: "chunk_id"`；q24 補 `eval_mode: "open_set_lenient"`（保留既有 `scope` 欄位或將其改名為 `eval_mode`，二擇一在 apply 階段決定）；q25/q26 補 `eval_mode: "enumeration"`；q27-q30 依其題型分別補對應 mode（明確區分：弧線題用 `open_set_lenient`、列舉題用 `enumeration`、其餘 `chunk_id`）
- [x] 2.3 對於 q24/q25/q26 既有的 `scope` 欄位：若 1.x 的 schema 不再保留 `scope`，則本 task 一併移除；若保留則 `scope` 與 `eval_mode` 必須同義（apply 時須在 design 補一行說明留哪個）
- [x] 2.4 跑 1.3 的 validator 對兩個 dataset 全綠才算完成

## 3. Runner 評分迴圈 dispatch

- [x] 3.1 在 `backend/eval/runners/run.py` 的 per-item 主迴圈（讀取 item 與呼叫 `_retrieve` 之後），改寫成依 `item["eval_mode"]` 分岔到三條評分路徑
- [x] 3.2 `eval_mode == "chunk_id"` 走既有 `recall_at_k` 路徑（含既有 negative 題 `None` 沉默排除行為），per-item record 加 `eval_mode: "chunk_id"` 欄位
- [x] 3.3 `eval_mode == "open_set_lenient"` 走新計算：若任一 retrieved chunk id 落入 `_to_lenient_ids(ground_truth_chunk_ids)` 集合則 `recall = 1.0`，否則 `0.0`；MRR 保留既有 `reciprocal_rank` 行為
- [x] 3.4 `eval_mode == "enumeration"` 走新計算：`retrieved_eps = _to_episode_ids(chunk_ids)`；`episode_set_recall = |set(retrieved_eps) ∩ set(expected_episode_ids)| / |expected_episode_ids|`；該題 `recall_at_k = None`（不進 chunk-based mean），改在 per-item record 新增 `episode_set_recall: float` 欄位；MRR 不計算（為 None）
- [x] 3.5 新增 helper 函式 `episode_set_recall(retrieved_eps: list[str], expected_eps: list[str]) -> float`，放在 `backend/eval/metrics/recall.py` 同檔（若 < 30 行）或新檔 `backend/eval/metrics/enumeration.py`；含 docstring 說明回傳值域 [0, 1] 與空 expected 處理（空時回 None）

## 4. Aggregate 與 markdown report 分段

- [x] 4.1 修改 `_aggregate(items)` (`backend/eval/runners/run.py`)：把 items 依 `eval_mode in {"chunk_id","open_set_lenient"}` vs `eval_mode == "enumeration"` 分兩群；分別計算 mean
- [x] 4.2 報表 JSON 結構：`metrics.chunk_based.{n, n_scored_retrieval, recall_at_k_mean, mrr, ...}` 與 `metrics.enumeration.{n, episode_set_recall_mean, ...}`；保留既有 `metrics.by_type` 結構以維持向後相容
- [x] 4.3 修改 `_markdown_report(report)`：把單行 `Recall@K (...)` 列拆兩行，分別標示 `Recall@K (chunk, n=X)` 與 `Episode Set Recall (enumeration, n=Y)`；若任一群 n=0 則該行顯示 `n=0` 與 `-`，不報錯
- [x] 4.4 更新 `run.py:22` 的 docstring 註解（"Negative items..."）說明新的 dispatch 行為與兩個 metric 群

## 5. Regression 守門 + baseline 跑一輪

- [x] 5.1 在 staging（local backend 或 dev tier）對 `this-not-that-cool.json` q01-q23 跑一輪 eval，比較改動前後 `recall_at_k_mean` 數字必須一致（容差 0），確認 chunk-based 行為無 regression
- [x] 5.2 跑 `_pending_review.json` q24-q30 一輪，確認 markdown report 出現 enumeration 段、`episode_set_recall_mean` 為合法浮點數、q25 ≤ 0.20 且 q26 ≤ 0.83（top_k=5 數學上限）
- [x] 5.3 把跑出來的 baseline 數字 append 進 `docs/case-studies/r33-baseline.md`（檔案若不存在則建立空檔加標題），格式：日期、commit hash、chunk-based recall、enumeration recall、各題 per-item 數字。此 case study 不進 git commit（遵循 docs/case-studies 規則）
- [x] 5.4 確認 `python -m backend.eval.runners.run` 在 `--canary 3` 與 full run 兩種模式下都跑得完，checkpoint 機制不被破壞

## 6. 收尾

- [x] 6.1 跑 `spectra validate eval-runner-enumeration-scope` 全綠
- [x] 6.2 把 `_pending_review.json` 內 30 題 review 完的部分透過 `build_golden_set.py --target-main` 或手動 merge 進 `this-not-that-cool.json`（若此步應該屬於另一個 change，apply 時拍板是否拉出本 change 範圍）
- [x] 6.3 commit + push，PR description 強調 metric report 表格從單行變兩行的破壞性 (release note 等級)
