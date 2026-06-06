## Context

`hyde-retrieval-landing`（2026-06-05 archive）落地 flag-gated HyDE：`resolve_semantic_embedding()` 在 `enable_hyde_retrieval=True` 時無差別生成 HyDE 文本、用其 embedding 取代 chunk-recall semantic 向量。三個 retrieve 進入點（`public_search_show`、`query_show` search 模式、`query_show` chat rule-based path）的流程都是：

```
embed base_vec → resolve_semantic_embedding（決定 HyDE）→ retrieve_hybrid 召回
```

關鍵：決定要不要 HyDE 的當下還沒做任何召回。prod A/B 證明無差別 HyDE 是雙面刃（標靶 b20 @1719 rank 78→17 有效；calibration b05 78.7→124.2 退步），故 flag 維持 off。本 change 把 HyDE 改成只在偵測到「詞彙失配」時才啟用。

`RetrievedChunk` 已含 `text`（chunk 文本）與 `rrf_score`；主案的詞面重疊度可純後處理 base 召回結果計算，不需動 `retrieve_hybrid` 的三段 RRF SQL。

## Goals / Non-Goals

**Goals:**

- 只在偵測到詞彙失配時啟用 HyDE，保住標靶失配題的 prefilter-rank gain，同時不傷 lexical 已對齊的 calibration 題。
- 用既有 `hyde_ab` harness 校準失配偵測門檻，門檻是資料校準出來的、非拍腦袋。
- 對齊未失配時零額外 LLM / embed / 召回成本；偵測與 HyDE 生成全程 fail-open，retrieve path 不得 5xx。

**Non-Goals:**

- 不 flip 任何 flag 預設值——`enable_hyde_retrieval` 與新 `hyde_conditional_activation` 皆 default off；上線 flip 是另一決策，需 prod A/B + 人工核可。
- 不改 `route_episodes` 行為（episode routing 永遠用 base_vec，與既有 spec 一致）。
- 不改 `retrieve_hybrid` 的 RRF SQL 或回傳結構（主案 b）；改 SQL 暴露 lexical 分數是備案 a，本 change 不實作，僅在校準失敗時評估。
- 不處理 b22 routing / b23 narrative（另條獨立 change）。

## Decisions

### D1. 失配偵測訊號 = query↔base 召回 top-k 詞面重疊度（主案 b）

新增純函式（位於 `hyde_retrieval.py`）：以既有 tokenizer 對 query 斷詞，計算 query token 集合中有多少比例出現在 base 召回 top-N hits 的 `text` 聯集裡，回傳 overlap ratio ∈ [0,1]。ratio < 門檻 → 判定詞彙失配。

選此訊號理由：直接對應 A/B 因果（「問句講法 ≠ 答案講法」＝ query 詞面在召回文本裡找不到）；純後處理、零 SQL 改動、最低風險。tokenizer 沿用專案既有中文斷詞（`app.services` 內現用於 lexical ts_query 建構的同一套），避免引入新斷詞行為。

備案 a（改 SQL 暴露 lexical rank/score 當訊號）僅在 D5 校準時主案分不開兩組才啟用，本 change 預設不走。

### D2. 兩階段召回流程（條件式啟用時）

新增 orchestrator（建議 `resolve_chunk_hits_conditional()` 於 `hyde_retrieval.py`，呼叫端在 `query.py` 三處），流程：

1. 以 base_vec 跑 `retrieve_hybrid` 得 base_hits（第一輪，本來就要做）。
2. `overlap = lexical_overlap_ratio(question, base_hits[:N])`。
3. 若 `overlap >= threshold`（lexical 對得上）→ 直接回 base_hits，`used_hyde=False`，零額外成本。
4. 若 `overlap < threshold`（失配）→ 生成 HyDE 文本（複用既有 `resolve_semantic_embedding` 的生成 + embed 邏輯）、以 HyDE 向量跑第二輪 `retrieve_hybrid`、回第二輪 hits，`used_hyde=True`。

`route_episodes` 與 lexical BM25 question 一律維持 base_vec / 原問題不變（與既有 spec D 一致）。

### D3. 設定旗標（保留既有、新增條件式）

`backend/app/core/config.py` 新增：

- `hyde_conditional_activation: bool = False`：條件式啟用總開關。僅 `enable_hyde_retrieval=True` 且本旗標 `True` 時走兩階段；其餘組合行為與現況位元等價（master off → 完全不進 HyDE；master on + conditional off → 現況無差別 HyDE）。
- `hyde_mismatch_overlap_threshold: float = <校準後填入>`：失配判定 cutoff，由 D5 校準決定，預設值在校準完成後寫入 config 與 spec。
- `hyde_mismatch_topn: int = <校準後填入>`：計算重疊度取 base 召回前 N 筆（預設建議 5，校準時一併掃）。

### D4. 觀測欄位

`HydeResult` 擴充：`conditional_mode: bool`（是否走兩階段）、`overlap_ratio: float | None`（量測到的重疊度）、`triggered_by_mismatch: bool`（是否因失配而開 HyDE）。`/admin/diagnose/prefilter-rank`（`diagnose_prefilter.py`）回傳這些欄位，供 A/B harness 觀測條件式效果。

### D5. 門檻校準（用既有 harness）

新增 `backend/scripts/hyde_ab/calibrate_threshold.py`：對 10 標靶 + 8 calibration 兩組各題量 overlap ratio + 在多個候選 cutoff（如 0.1/0.2/0.3/0.4/0.5）下模擬「會不會開 HyDE」，輸出每個 cutoff 下標靶啟用率 / calibration 誤啟用率 / 預期 must-rank gain。選能把兩組分開的 cutoff。結果寫 `docs/case-studies/hyde-conditional-activation-calibration.md`（不進 git commit，依專案規範）。選定 cutoff 回填 D3 的 config 預設值與 spec。

## Implementation Contract

- **Behavior**：`enable_hyde_retrieval=True` 且 `hyde_conditional_activation=True` 時，retrieve path 先做 base 召回，僅在 query↔top-k 詞面重疊度 < `hyde_mismatch_overlap_threshold` 時補做 HyDE 第二輪召回並回傳其結果；重疊度達標時回傳 base 召回結果且不做任何額外 LLM/embed/召回。其餘 flag 組合行為與現況位元等價。
- **Interface**：
  - `config.Settings` 新增 `hyde_conditional_activation: bool`、`hyde_mismatch_overlap_threshold: float`、`hyde_mismatch_topn: int`。
  - `hyde_retrieval.py` 新增 `lexical_overlap_ratio(question: str, hits: list[RetrievedChunk]) -> float` 純函式與兩階段 orchestrator（回傳含 hits + 擴充後的 `HydeResult` 觀測欄位）。
  - `HydeResult` 新增 `conditional_mode: bool`、`overlap_ratio: float | None`、`triggered_by_mismatch: bool`。
  - `query.py` 三處 retrieve 進入點改呼叫兩階段 orchestrator。
  - `calibrate_threshold.py` CLI：輸入兩組題、輸出各 cutoff 的啟用率/gain 表。
- **Failure modes**：詞面重疊度計算或 HyDE 生成/embed 任何失敗一律 fail-open 回 base 召回結果，`triggered_by_mismatch=False`，記 warning，不 raise、不 5xx（沿用既有 `resolve_semantic_embedding` fail-open 模式）。
- **Acceptance criteria**：
  - 單元測試：master off → 不進 HyDE；master on + conditional off → 現況無差別 HyDE（既有行為不回歸）；master on + conditional on + 高重疊 → 不開 HyDE；master on + conditional on + 低重疊 → 開 HyDE 第二輪；HyDE 生成失敗 → fail-open 回 base hits 不 raise。
  - `lexical_overlap_ratio` 對「query 詞全在 top-k 文本」回傳接近 1.0、對「query 詞全不在」回傳接近 0.0。
  - 校準腳本對標靶組多數題 overlap < 選定 cutoff、對 calibration 組多數題 overlap >= cutoff（兩組可分）。
- **Scope boundaries**：in scope = 三個 retrieve 進入點的兩階段條件式啟用 + 失配偵測 + 門檻校準 + 觀測欄位。out of scope = flip 預設、改 RRF SQL、b22/b23、route_episodes 行為。

## Risks / Trade-offs

- **失配題多付一次召回延遲**：條件式啟用下，被判失配的題要召回兩次（+1 LLM +1 embed +1 retrieve）。可接受——只有失配題付，lexical 對齊題零額外成本；且仍維持 flag off，上線前可由 A/B 觀測延遲分佈。
- **詞面重疊度是 lexical proxy，非語意**：可能對「同義改寫但語意對齊」題誤判為失配而多開 HyDE（誤啟用），或對「詞面巧合重疊但語意失配」題漏開。D5 校準的目的就是量這兩類誤判率；若主案 b 在校準時無法把兩組分開，啟用備案 a（lexical 分數門檻）。
- **門檻過擬合 18 題**：cutoff 校準樣本小，可能對這 18 題過擬。緩解：flag 維持 off，正式上線需另跑 prod A/B 驗證；門檻設為 config 可調，不寫死。
