## Why

Golden set 已擴到 30 題並引入兩種新型評分模式（q24 `open_set_lenient`、q25/q26 `enumeration`），但 runner (`backend/eval/runners/run.py`) 仍只有 chunk-id 對位一條路徑。q25/q26 的 `ground_truth_chunk_ids` 為空，跑下去會被 `recall_at_k` 回傳 `None` 並沉默排出 aggregate — 等於白跑。需要把評分模式變成 schema 第一公民，讓 runner 看得懂該怎麼算分。先 ship 評分路徑，才能在後續 R3.3 metadata-filter 上線時量出 q25/q26 baseline 變化，作為 retrieval 改動的驗收訊號。

## What Changes

- **新增 `eval_mode` 欄位**到 golden set item schema（`backend/eval/datasets/_schema.json`），值為 enum `["chunk_id", "open_set_lenient", "enumeration"]`，每題必填、無預設
- **條件式 required 規則**：`eval_mode == "enumeration"` 時 `expected_episode_ids` 必填且非空陣列；其他 mode 時 `ground_truth_chunk_ids` 必填（可空陣列以保留 negative 題語意）
- **Migrate 既有資料**：`this-not-that-cool.json` 全部 q01-q23 補 `eval_mode: "chunk_id"`；`_pending_review.json` 內 q24 補 `open_set_lenient`、q25/q26 補 `enumeration`、q27-q30 補對應 mode
- **Runner 評分迴圈 dispatch**：在 `run.py` 主迴圈依 `eval_mode` 分岔到三條評分路徑，新增 helper `episode_set_recall(retrieved_eps, expected_eps)` 計算 `|retrieved ∩ expected| / |expected|`
- **新 metric `episode_set_recall`** 獨立於既有 `recall_at_k`；aggregate 拆 chunk-based / enumeration 兩段分別計算 mean
- **Markdown report 分段呈現**：表格從單行 Recall 變兩行 — chunk-based n=X / enumeration n=Y
- **既有負面題行為保留**：`eval_mode=chunk_id` + 空 `ground_truth_chunk_ids` 仍回 `None`、沉默排除 — 不動

## Non-Goals

- **動態 top_k**（per-item 提到 `len(expected_episode_ids)`）— 留給未來 `eval-runner-dynamic-top-k` change；本次 top_k 維持全域 5。後果：q25 expected 25 集 → `episode_set_recall` 數學上限 0.20，可接受作 R3.3 對照組訊號
- **不設 hit 門檻 / pass-fail gate**：報原始 recall 數字即可；R3.3 上線後的數字變動才是訊號，不在 runner 層做 gating
- **R3.3 metadata-filter 改動**（episodes.guests 欄位、BM25 多欄位 weighting）：不在本 change 範圍
- **golden set 內容改動**（新增/移除題目、調整 anchor）：本 change 只 migrate 既有題加 `eval_mode` 欄位，不動題目語意

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `rag-eval-dataset`: golden set item schema 新增 `eval_mode` 必填欄位 + `expected_episode_ids` 條件 required 規則
- `rag-eval-runner`: runner 新增依 `eval_mode` 分岔的評分路徑、新 metric `episode_set_recall`、aggregate 與 markdown report 分段呈現

## Impact

- Affected specs: `rag-eval-dataset`, `rag-eval-runner`
- Affected code:
  - Modified:
    - `backend/eval/datasets/_schema.json`（加 `eval_mode` enum + 條件 required）
    - `backend/eval/datasets/this-not-that-cool.json`（既有 q01-q23 補欄位）
    - `backend/eval/datasets/_pending_review.json`（q24-q30 補欄位）
    - `backend/eval/runners/run.py`（評分迴圈 dispatch、aggregate 分段、markdown report 分段）
    - `backend/eval/metrics/recall.py`（保留現行行為，新增 `episode_set_recall()`）或新檔 `backend/eval/metrics/enumeration.py`
  - New: 視實作決定是否新增 `backend/eval/metrics/enumeration.py`
  - Removed: (none)
- 跑完一輪 n=30 eval 作為 baseline，供 R3.3 metadata-filter ship 時對照
