## Summary

針對 `search_with_topic_prefilter` path 在主集內 `retrieve_hybrid` top-5 漏掉 GT chunk 的問題，在 prefilter 找到候選集後改抓 top-N（N=20）再做 LLM rerank 收斂回 5，提升 cross_episode `chunk_recall_grouped` mean。

## Motivation

Follow-up from `retrieval-cross-episode-episode-prefilter`（archive `2026-05-26-retrieval-cross-episode-episode-prefilter`，commit `1c6e311`）。

該 change ship 後 prod 驗證：

- agent 自發採用率 cross_episode 50%（b20、b21 用新 tool）
- b20 案例 5 chunks 全部從正確主集 EP134 抽出，無別集污染（mechanism 對）
- **但** cross_episode `chunk_recall_grouped` mean = **0.244 持平**（b20=0.000 / b21=0.400 / b23=0.333）
- 結論落入 task 3.3 預寫的規則 (c)：mechanism 對但 `retrieve_hybrid` 主集內 top-5 仍排不出 GT chunk

換句話說：跨集污染解決了，瓶頸移到「主集內 RRF top-5 排序漏 GT」。直接增加 top-5 → top-20 + rerank 是最對症的下一步。

Evidence：`docs/case-studies/retrieval-cross-episode-episode-prefilter-2026-05-26.md` 第 6 節。

## Proposed Solution

只在 `search_with_topic_prefilter` 路徑加 rerank 階段（不動 `search_across_episodes` / `search_within_episode` 等其他 tool），避免 blast radius：

1. **Diagnostic gate**（先做不寫死）：對 b20/b21/b23 三題的主集內 chunk pool，dump GT chunk 在 top-5/20/50/100 的實際 rank。若 GT 不在 top-50 → mechanism 假設錯，pivot 到方向 D（chunk-level overlap merging）。若 GT 落在 6-20 名 → 證實 rerank 可行，繼續實作。
2. **Top-N expand**：`_search_with_topic_prefilter` 內把 `retrieve_hybrid(k=inp.k)` 改成 `retrieve_hybrid(k=20)`（hard-coded 20，不暴露給 LLM）。
3. **LLM rerank**：呼叫 `gemini-2.5-flash-lite`（既有 topic_seg / summary 棧），傳 question + 20 個 chunk 的 text，回傳重排後的 chunk_id list；取前 `inp.k`（預設 5）回給 agent。
4. **Envelope 擴充**：tool 回傳新增 `rerank_applied: bool` 跟 `rerank_input_count: int` 兩個 field（debug 用，跟現有 `prefilter_episode_count` / `fallback_to_full_pool` 並列）。
5. **Eval 驗證**：跑同 8 題 subset（b20/b21/b22/b23/b29/mt02-04）比 0.244 baseline。

## Non-Goals

- 不動 prefilter mechanism（已驗證）
- 不動 SYSTEM_PROMPT（避免 prompt 飽和；rerank 完全在 tool 層內部，agent 無感）
- 不動 `search_across_episodes` / `search_within_episode` / 其他 retrieval tool 的 top-k（只動 prefilter path）
- 不引入新 dependency（cross-encoder / Cohere rerank 留作未來方向，本次用既有 LLM stack）
- 不調 RRF weight（前一個 archive `retrieval-cross-episode-recall-improvement` 7 個 RRF 候選全 REJECT，weight lever 已驗證無 headroom）

## Alternatives Considered

- **方向 B：對 prefilter path 單獨調 RRF weight** — 拒絕。`retrieval-cross-episode-recall-improvement` 已測 description weight 0.85/1.0/1.2/1.5/2.0 全 REJECT，weight 不是 lever。
- **方向 C：BM25 在主集內 boost** — 拒絕。GT chunk 漏進 top-5 不一定是詞彙匹配問題，BM25 boost 可能只是重排同樣 chunks。
- **方向 D：chunk-level 重疊段落合併** — 暫緩。需先做 diagnostic 證實「相鄰段落擠壓 GT 排序」是主因。Diagnostic gate（task 1）就是要排除這條路；如果 diagnostic 顯示 GT 不在 top-50，這 change 整體 pivot 到 D，proposal 會重寫。
- **方向 A 變形：cross-encoder（BGE-reranker）** — 留作未來方向。引入新模型 / 新依賴成本高，先用既有 LLM stack 證 rerank lever 有效再升級。

## Impact

- Affected specs:
  - `rag-query`（MODIFIED — `retrieve_hybrid` 不變，但新增 prefilter-path rerank wrapper 行為描述）
  - `chat-agentic-routing`（MODIFIED — `search_with_topic_prefilter` envelope 新增兩個 field）
- Affected code:
  - Modified: `backend/app/services/chat_agent/tools.py`（`_search_with_topic_prefilter` 改 top-20 + 呼叫 rerank）
  - New: `backend/app/services/rag/rerank.py`（LLM rerank wrapper）
  - New: `backend/tests/test_chat_agent_topic_prefilter_rerank.py`（rerank path unit test）
  - New: `backend/scripts/diagnose_prefilter_rank.py`（task 1 diagnostic 腳本）
