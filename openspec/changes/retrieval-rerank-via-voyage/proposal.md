## Summary

把 `_search_with_topic_prefilter` 內被 disable 的 rerank 階段重新接上，但底層 swap 為 Voyage rerank-2.5 API（dedicated cross-encoder reranker）取代上一輪證實不可行的 LLM-as-reranker。

## Motivation

Follow-up from `retrieval-cross-episode-chunk-recovery`（archived 2026-05-27，commit `5d00ac9`）。該 change apply 階段 6 次 smoke iteration 跨 2 個 model（gemini-2.5-flash-lite、gpt-4o-mini）× 3 個 N（50/30）× 3 個 timeout（1.5/3/6s）全部 TimeoutError 或 invalid JSON，結論：

> Zeabur AI Hub 對「中等 prompt + 結構化 JSON 輸出」的 latency profile 撐不住 chat 即時 query 場景。

詳細 6 iter table + cross-encoder VPS 自架評估在 `docs/case-studies/retrieval-cross-episode-chunk-recovery-2026-05-26.md` § 6-7。

該 change 留下了 (a) `backend/app/services/rag_rerank.py` wrapper 結構 + 5 unit test 全綠 (b) envelope 欄位 `rerank_applied` / `rerank_input_count` 契約 (c) prefilter top-N 擴展邏輯架構。這個 follow-up 直接 reuse — 換掉 wrapper 內部 LLM call 為 Voyage call、重啟動 N=30 prefilter top-N 擴展、envelope 欄位填實際值即可。

## Proposed Solution

1. **依賴 + key**：requirements.txt 加 `voyageai`；backend/.env + Zeabur 4 service env 加 `VOYAGE_API_KEY`
2. **改造 `rag_rerank.py`**：
   - 留既有 `llm_rerank` 為 reference（不再被 prefilter 呼叫，可未來移除）
   - 新增 `async def voyage_rerank(question, chunks, k, *, client, model='rerank-2.5', timeout_s=3.0) -> tuple[list[dict], bool]` 同樣的 fail-open contract
   - 用 voyageai async client `client.rerank(query=..., documents=[chunk.text...], model='rerank-2.5', top_k=k)` → 解析回傳 indices → 映射回原 chunks list 取 top-k
3. **重啟 `_search_with_topic_prefilter` rerank pipeline**：
   - prefilter 命中時：`retrieve_hybrid(k=30, episode_id_filter=...)` → `voyage_rerank(query, chunks, k=inp.k)` → envelope 帶 `rerank_applied=True / rerank_input_count=30`
   - empty candidates fallback：保持 `k=inp.k` 不 rerank、envelope `rerank_applied=False / rerank_input_count=0`
4. **單元 test**：`backend/tests/test_voyage_rerank.py` 5 case（happy / timeout fallback / API error fallback / unknown index ignored / partial back-fill）+ 改 `test_chat_agent_topic_prefilter_rerank.py` 重啟 rerank-applied 場景
5. **Prod 驗證 + case study**：8 題 subset eval 對 baseline 0.244，gate ≥ 0.40

## Non-Goals

- 不解 b20 retrieval miss（屬另一個 follow-up change `cross-episode-b20-retrieval-investigation`，b20 有 2/4 GT chunks 不在 retrieve_hybrid top-100 — 是 retrieval miss 不是排序問題）
- 不動其他 retrieval tool（`search_across_episodes` / `search_within_episode` / `search_in_episodes` 等）的排序邏輯
- 不重啟 LLM-as-reranker（已證實 AI Hub 不可行）
- 不自架 cross-encoder（VPS 4GB RAM 不夠跑 BGE-v2-m3 fp16 + 月成本同等級於 Voyage API 但 ops 複雜度高）
- 不擴大到 multi-show 通用化（目前 1 個 show）
- 不調 RRF weight 或其他 retrieve_hybrid 內部參數

## Alternatives Considered

- **Cohere Rerank 3.5**：latency / 品質類似 Voyage，但 $2 / 1k searches × 40 倍貴
- **Jina Reranker**：成本最低（$0.001 / 1k），但 Python SDK 較不成熟、async 支援待驗
- **自架 BGE-reranker-v2-m3 on Linode VPS**：4 GB RAM 已被 6 個 service 佔用、剩 400-800 MB 撐不下 1.1 GB fp16 model；要先升級 VPS 到 8 GB （+$12 / 月）才有頭寸；CPU 推論 50 chunks 約 1.5-3s 且會跟 backend API 搶 CPU；ops 複雜度（cold start / docker image +1-2 GB / weights download cache）遠高於 Voyage API
- **加大 LLM rerank timeout 到 12-15s**：13s user-facing chat 延遲不可接受
- **Cross-encoder via Hugging Face Inference Endpoint**：$0.06/hr 起跳，per-call latency 不一定優於 Voyage，且要管 endpoint lifecycle

完整評估見前 change case study § 7。

## Impact

- Affected specs:
  - `chat-agentic-routing`（MODIFIED — 把上一個 change 標 reserved 的 envelope 欄位實際啟用，rerank 階段在 prefilter 路徑變成 active）
- Affected code:
  - Modified: backend/app/services/rag_rerank.py（新增 voyage_rerank 函式 + 既有 llm_rerank 標 deprecated）
  - Modified: backend/app/services/chat_agent/tools.py（_search_with_topic_prefilter 重啟 N=30 + 改 call voyage_rerank）
  - Modified: backend/requirements.txt（加 voyageai package）
  - Modified: backend/.env.example（加 VOYAGE_API_KEY 範例）
  - New: backend/tests/test_voyage_rerank.py（5 case unit test）
  - Modified: backend/tests/test_chat_agent_topic_prefilter_rerank.py（重啟 rerank-applied 場景）
