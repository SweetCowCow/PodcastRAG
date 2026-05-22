## Why

Phase 2 翻 default 後 chat-mode regression baseline 預設改用 `backend/eval/datasets/extended-multi-turn-40.json`（34 record / 40 turn / 9 design_type），但本 dataset **缺 `ground_truth_chunk_ids` 欄位**，導致 `run_chat_agent_eval.py` 的 nested schema 路徑無法計算 Recall@5，目前 `aggregate.recall_at_k_mean` 寫死 `None`。少了這條主指標，未來改 retrieval（chunking / embedding / RRF）只能回頭跑舊 `this-not-that-cool.json` 30 題，但那組沒有 multi-turn 維度跟 tool coverage。本 change 補齊 dataset + 改 runner，讓單一 dataset 同時量 Recall@5 + answer_match + tool coverage + LLM judge quality 四條指標。

## What Changes

- 新增 `backend/eval/scripts/copy_ground_truth.py`：讀 multi-turn-40 內 `source: "existing:<old-id>"` 欄位、對照 `this-not-that-cool.json` 取得既有 `ground_truth_chunk_ids` 並 copy 進 multi-turn-40 對應 turn（涵蓋約 14 turn，純自動化）。
- 人工 audit 12 個 `source: "new"` single-turn 題 + 4 組 multi-turn 第 1 turn，補對應 chunk_id list（約 16 turn）。
- multi-turn 後續 turn（t2/t3 共 6 turn）保持 `ground_truth_chunk_ids: null`（episode-level 性質，不適合 chunk_id 量法）；runner 自動 skip。
- 改 `backend/scripts/run_chat_agent_eval.py` 的 nested 路徑：若 turn 有 `ground_truth_chunk_ids` → 跑 `/search` 抽 top-K → 用既有 `_recall_at_k` 計算；aggregate 補 `recall_at_k_mean`（只 across scored turns），其餘指標不動。
- dataset `version` 1 → 2，`notes` 補欄位。
- 補既有 unit / integration test 覆蓋兩個改點。

## Non-Goals

- 不重建 dataset（保留現有 34 record / 40 turn 結構）
- 不動 LLM judge schema（`answer_quality` / `hallucination_severity` / `context_carry_hit` 維持）
- 不對 multi-turn t2/t3 補 episode-level ground truth（性質不對；待未來「multi-turn episode-level scoring」獨立 change）
- 不擴增題量、不改 design_type 分布

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `rag-eval-dataset`: dataset 第 1 → 2 版補 30 turn 的 `ground_truth_chunk_ids`（14 自動 copy + 16 人工 audit）；schema 維持，欄位語意明文化 nullable。
- `rag-eval-runner`: nested-schema 路徑啟用 Recall@5 計算（per-turn `ground_truth_chunk_ids` 存在則量）；aggregate `recall_at_k_mean` 不再 hardcode null。

## Impact

- Affected specs: `rag-eval-dataset`（MODIFIED）、`rag-eval-runner`（MODIFIED）
- Affected code:
  - Modified:
    - backend/eval/datasets/extended-multi-turn-40.json（補欄位 + version bump）
    - backend/scripts/run_chat_agent_eval.py（nested 路徑 Recall@5 啟用）
  - New:
    - backend/eval/scripts/copy_ground_truth.py（一次性自動 copy script）
    - backend/tests/test_eval_runner_nested_recall.py（驗 nested 路徑 Recall@5 計算 + aggregate）
  - Removed:
    - 無
