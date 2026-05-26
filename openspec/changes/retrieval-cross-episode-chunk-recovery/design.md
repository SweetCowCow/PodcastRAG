## Context

新 tool `search_with_topic_prefilter`（archive `2026-05-26-retrieval-cross-episode-episode-prefilter`，commit `1c6e311`）已 ship。Prod 8 題 subset eval：

- agent 自發採用率 cross_episode 50%（b20/b21 採用，b22 走 listing, b23 走 fallback）
- b20 案例：5 chunks 全部來自正確主集 EP134（無別集污染）
- **但** `chunk_recall_grouped` mean 0.244 持平（b20=0.000 / b21=0.400 / b23=0.333）

GT chunk 沒進 top-5，瓶頸從「跨集污染」轉到「主集內 RRF 排序」。

**Stakeholder**：使用者問跨集主題型問題（e.g. 「迪拉怎麼描述中老年人開工想法」）時，回答品質受 chunk 排序影響。

**Constraints**：
- 不引入新模型依賴（cross-encoder 留作未來）
- 不動 SYSTEM_PROMPT
- 只改 `search_with_topic_prefilter` path，其他 retrieval tool 不變
- Rerank 額外延遲 < 1.5s（既有 retrieve_hybrid p50 ~500ms）

## Goals

- cross_episode `chunk_recall_grouped` mean（b20/b21/b23 subset）從 0.244 → ≥ 0.40
- `factual_correctness` mean 不退步（保持 ≥ 0.80）
- prefilter path 整體 p95 latency < 2.5s（含 rerank）

## Non-Goals

- 不改其他 retrieval tool 的排序邏輯
- 不引入 cross-encoder / dedicated reranker model
- 不在 prompt layer 加 affordance
- 不調 RRF weight（前一個 sweep archive 已驗證無 headroom）

## Decisions

### Use gemini-2.5-flash-lite for LLM rerank

選 LLM rerank（既有 stack）而非 cross-encoder。理由：

- 既有 topic_seg / summary 都跑 `gemini-2.5-flash-lite`（Zeabur AI Hub），無新依賴
- 單次 rerank ~20 chunks，prompt 2-3k token，p50 latency ~600-900ms（依現有 stack 經驗）
- 成本：~$0.0003/query（gemini-flash-lite pricing），cross_episode 流量低，月成本 < $1

**Alternatives 拒絕**：
- Cross-encoder（BGE-reranker-large）：要 host 新 model 或接 Cohere API，infra 成本不對等
- 純 heuristic re-fuse（BM25 + RRF 重算）：lever 跟 `retrieve_hybrid` 內部一樣，predict 效益接近 0

### Top-N expand to 20 candidates

抓 retrieve_hybrid top-20 餵 rerank。理由：

- task 1 diagnostic 會先驗證 GT chunk 是否落在 top-20-50；若 GT 在 top-50 但不在 top-20，N 上調到 50。預設 20 是基於「合理 LLM context window + cost / latency 平衡」。
- 20 chunks × ~150 tokens/chunk = ~3k token，gemini-flash-lite 16k context 充裕

**Alternative 拒絕**：
- N=50：context 量 ×2.5、latency 預估翻倍。先試 20，diagnostic 證明需要再上調

### Limit rerank to search_with_topic_prefilter path

範圍隔離：rerank logic 只在 `_search_with_topic_prefilter` 內呼叫，`_search_across_episodes` / `_search_within_episode` / `_search_in_episodes` 不變。理由：

- 本次目標是改善 cross_episode chunk_recall，瓶頸在 prefilter path 已明確
- 其他 tool 的 retrieval 表現未量測，動了等於攬風險
- Envelope `rerank_applied` field 讓 debug_trace 可區分

### Diagnostic gate before implementation

實作前先跑 `diagnose_prefilter_rank.py` 對 b20/b21/b23 三題 dump GT chunk 在 top-5/20/50/100 的 rank。

**Gate 判讀**：
- GT 全在 top-20：直接做 rerank，預期 mean ≥ 0.40 達標
- GT 在 top-20-50：N 上調到 50，做 rerank
- GT 不在 top-50：mechanism 假設錯（GT 根本不在主集 retrieve 池），**pivot 整個 change**，本 design 重寫到方向 D（chunk-level overlap merging）

避免在「GT 不在 retrieval 池」的情境下硬上 rerank — rerank 不會無中生有把不在池的 chunk 撈進來。

### Rerank prompt schema

LLM 輸入：question + N 個 chunk（chunk_id + text 前 200 字）
LLM 輸出：JSON `{"ranked_chunk_ids": ["id1", "id2", ...]}`，回前 k 個（預設 5）

若 LLM 輸出 malformed JSON 或漏 chunk_id → fallback 回原 RRF top-k 順序（不 throw exception），同時記錄 `rerank_applied=false` 在 envelope。

## Implementation Contract

**Observable behavior**：
- `search_with_topic_prefilter` 呼叫成功時，回傳 chunks 數量仍為 `inp.k`（預設 5），但排序由 LLM rerank 決定（rerank 成功時）或 RRF 原順序（rerank 失敗 fallback）
- Envelope 額外回傳 `rerank_applied: bool`（rerank 成功為 true）跟 `rerank_input_count: int`（送進 rerank 的 chunk 數，預期 = N=20，若主集池不足 N 個則為實際數）
- 既有 envelope field `prefilter_episode_count` / `fallback_to_full_pool` 不變

**Interface**：
- `_search_with_topic_prefilter(inp, ctx)` 簽名不變
- 新增 `backend/app/services/rag/rerank.py` 提供 `async def llm_rerank(question: str, chunks: list[dict], k: int) -> list[dict]`
- LLM call 走 `app/services/llm.py` 既有 client，model `gemini-2.5-flash-lite`

**Error / failure modes**：
- LLM call 超時 / 5xx：fallback 回原 RRF 順序，envelope `rerank_applied=false`
- LLM 輸出 malformed JSON：同上 fallback
- LLM 輸出含未知 chunk_id：忽略未知 ID，取已知部分，缺額用原 RRF 補

**Acceptance criteria**：
- `pytest backend/tests/test_chat_agent_topic_prefilter_rerank.py` 6 case 全綠（rerank happy path、top-N expand、LLM 失敗 fallback、malformed JSON fallback、envelope field、chunk shape）
- Prod 8 題 subset eval：cross_episode chunk_recall mean ≥ 0.40，factual ≥ 0.80
- prefilter path p95 latency < 2.5s（從 debug_trace `stage_timings` 量）

**In scope**：
- `_search_with_topic_prefilter` 改 top-20 + rerank
- 新增 `rerank.py` 模組
- Diagnostic 腳本
- Unit test + prod eval + case study

**Out of scope**：
- 其他 retrieval tool 的排序
- Cross-encoder 引入
- SYSTEM_PROMPT 修改
- 全節目 baseline 重跑（只跑 subset 8 題）

## Risks / Trade-offs

- **Risk**：LLM rerank latency 不穩定，p95 可能 > 2.5s 預算 → Mitigation：rerank call 加 1.5s timeout，超時 fallback 原 RRF，envelope 記錄供觀測
- **Risk**：LLM 對中文 chunk 排序判斷可能有偏（譬如偏好特定關鍵字）→ Mitigation：先跑 diagnostic + subset eval 驗證實際效果，無效就 revert
- **Risk**：cost 飄高（若 cross_episode 流量上升）→ Mitigation：envelope `rerank_input_count` 可監控；月底回顧若 > $5 評估降到 N=10 或加 cache
- **Risk**：rerank 對 b22（listing）/ b29（leading）路徑無影響但會出現在 trace → Mitigation：這兩題本來就不走 prefilter path，rerank 不會 trigger，無風險
- **Trade-off**：rerank 增加 ~600-900ms latency 換 chunk_recall 改善。若 diagnostic 顯示 GT 在 top-5 內，rerank 無效益但仍付 latency cost。設計上 diagnostic gate 會擋掉這條路（GT 全在 top-5 → 不該做這個 change）

## Migration Plan

1. Implement + unit test（local）
2. Deploy backend（Zeabur git push，純 Python 變更無 migration）
3. Smoke：debug_trace 跑 b20 觀察 envelope `rerank_applied=true` + tool_calls trace 含 rerank latency
4. Subset eval 8 題對 baseline
5. 若 metric 達標 → archive；若不達標 → revert commit + 把結果寫進 case study 當 negative finding

**Rollback**：單一 commit revert 即可（rerank 是新增模組 + 一處 call site，無 schema 變更）。

## Open Questions

- LLM rerank prompt 細節（chunk text 截斷長度、是否帶 episode_id 給 LLM 看）會在 implementation 階段對 b20 案例迭代決定；diagnostic 跑出來後可能影響 N 值
- 若 diagnostic 顯示 GT 不在 top-50，change pivot 到方向 D，本 design 需要重寫 — 是否要先在 apply 之前獨立跑 diagnostic 再決定要不要繼續？目前 task 1 就是這個 gate，diagnostic 失敗會在 task 1 結束時 surface 給 user 拍板
