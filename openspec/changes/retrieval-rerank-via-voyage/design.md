## Context

Follow-up from `retrieval-cross-episode-chunk-recovery`（archived 2026-05-27，commit `5d00ac9`，NEGATIVE FINDING）。

該 change 證實 Zeabur AI Hub 跑 LLM-as-reranker 不可行（6 iter table 在前 change case study § 6）。本 change 改走 dedicated rerank API — Voyage rerank-2.5，預期 latency p50 ~150ms、月成本 < $5。

**已有 infrastructure 直接 reuse**：

- `backend/app/services/rag_rerank.py` 已有 wrapper 結構（5 unit test 全綠 — happy / timeout / malformed / unknown id / backfill），fail-open contract 已定義
- `_search_with_topic_prefilter` envelope 已預留 `rerank_applied` / `rerank_input_count` 欄位（spec 明文 reserved）
- prefilter top-N 擴展邏輯架構（目前 disable，重啟 N=30）

## Goals

- cross_episode `chunk_recall_grouped` mean（b20/b21/b22/b23/b29/mt02-04 8 題 subset）從 0.244 → **≥ 0.40**
- factual_correctness mean 不退步（保持 ≥ 0.80）
- prefilter path p95 latency < **2.0s**（含 Voyage rerank ~150ms + retrieve_hybrid ~500ms）
- envelope `rerank_applied=True` 比率 ≥ 90%

## Non-Goals

- 不解 b20 retrieval miss（b20 4/4 GT chunks 有 2 個不在 retrieve_hybrid top-100 — 屬另一個 follow-up）
- 不動其他 retrieval tool（`search_across_episodes` / `search_within_episode` 等）
- 不調 RRF weight 或 retrieve_hybrid 內部參數
- 不研究其他 rerank provider（Cohere / Jina / 自架已在前 change case study § 7 排除）
- 不引入新 capability，只 MODIFY 既有 `chat-agentic-routing`

## Decisions

### Voyage rerank-2.5 model selection

選 Voyage 而非 Cohere / Jina / 自架。理由：

- **Voyage rerank-2.5** multilingual model：繁中支援強，p50 latency ~150ms，cost $0.05 / 1k searches
- **Cohere Rerank 3.5** 拒絕：品質類似但 $2 / 1k 貴 40 倍
- **Jina Reranker** 拒絕：成本最低（$0.001 / 1k）但 Python SDK async 支援待驗，未來可比較但不是第一發
- **自架 BGE-v2-m3** 拒絕：VPS 4GB RAM 不夠跑 1.1GB fp16 model、要升級 VPS、ops 複雜度遠高於 API（前 change case study § 7.2 評估完整）

### voyage_rerank function in rag_rerank module

不 rewrite 整個檔案。具體：

- 留 `llm_rerank()` 為 deprecated reference（不被 caller 呼叫但 5 unit test 保留供 regression）
- 新增 `voyage_rerank()` 採同樣 signature pattern：`async (question, chunks, k, *, client, model='rerank-2.5', timeout_s=3.0) -> tuple[list[dict], bool]`
- Fail-open contract 跟 `llm_rerank` 一致：API error / timeout / parse error 全 fall back 原 RRF top-k 加 `applied=False`

**Why same shape**：caller `_search_with_topic_prefilter` 只要改一行（`llm_rerank` → `voyage_rerank`），其他邏輯不變

### Top-N expand to 30 candidates

重啟 N=30 拿前 change diagnostic 推算的 perfect rerank ceiling（b21=0.6, b23=0.667, b20=0.25, mean=0.506）— 仍在 ≥ 0.40 gate 內、且 30 chunks 對 Voyage API 是極短 payload（30 × 文字 200 字 ≈ 6KB），latency 預估 150-250ms

**Alternative 拒絕**：
- N=50：marginal gain（ceiling 0.683 vs 0.506）但 Voyage 是按 query 計費不是按 doc，無成本差。先用 30 保守驗證再考慮提升
- N=100：同上但 b20 ceiling 0.50 帶來 marginal gain 0.083，且還是受限於 retrieve_hybrid 漏掉 chunk 的問題

### VOYAGE_API_KEY environment variable

用 `voyageai.AsyncClient(api_key=os.environ["VOYAGE_API_KEY"])` 直接讀 env，**不**走 `ai_steps` DB config table。理由：

- ai_steps 表只支援 chat / embedding / whisper 三個 step_type，加 rerank 要動 schema + admin UI
- Voyage 是純 API key，沒有 base_url / model 可選配置，env var 夠用
- 跟 OPENAI_API_KEY embedding 走 env 的 precedent 一致（per memory `reference_env_openai_key.md`）

### rerank documents payload uses chunk text

送 Voyage 的 documents = `[chunk.text]`（純文字陣列，不含 chunk_id）。Voyage 回傳 list of `RerankResult` 內含 `index` + `relevance_score`。caller 用 index 映射回原 chunks list。

**Why not 拼 episode_title / metadata 進 doc**：保持送入 payload 緊湊；rerank 不用 metadata 也能排序。未來如需要可加 `(episode_title) text` prefix 但本次先省。

## Implementation Contract

**Observable behavior**：

- `search_with_topic_prefilter` 呼叫成功且 prefilter 命中時：(a) `retrieve_hybrid` 用 `k=30` 擴展 (b) 用 Voyage rerank → 取前 `inp.k` 回給 LLM agent (c) envelope `rerank_applied=True` + `rerank_input_count=30`
- empty candidates fallback 路徑：envelope `rerank_applied=False / rerank_input_count=0`，行為不變
- Voyage API 失敗（timeout / 5xx / parse error）：fall back 原 RRF top-k，envelope `rerank_applied=False / rerank_input_count=30`，不 throw exception 到 agent loop

**Interface**：

- `backend/app/services/rag_rerank.py`：新增 `async def voyage_rerank(question: str, chunks: list[dict], k: int, *, client, model: str = "rerank-2.5", timeout_s: float = 3.0) -> tuple[list[dict], bool]`
- Caller 在 `_search_with_topic_prefilter` 內 import voyageai + 建 client（讀 `VOYAGE_API_KEY` env）+ 呼叫 voyage_rerank
- envelope 欄位名稱 **不變**（spec 已 reserved），只是值從常數 `False/0` 改為實際 voyage 結果

**Error / failure modes**：

- `VOYAGE_API_KEY` 未設：`voyage_rerank` log warning + 直接 fall back（envelope `applied=False, count=30`），不阻斷 agent
- Voyage API timeout（> 3s）：同上
- Voyage 回傳 unknown index：略過，剩餘用原順序回填
- Voyage 5xx / 4xx：同 timeout fallback

**Acceptance criteria**：

- `pytest backend/tests/test_voyage_rerank.py` 5 case 全綠
- `pytest backend/tests/test_chat_agent_topic_prefilter_rerank.py` 6 case 全綠（重啟 rerank-applied 場景）
- Prod 8 題 subset eval：cross_episode `chunk_recall_grouped` mean ≥ 0.40 且 `factual_correctness` mean ≥ 0.80
- prefilter path p95 latency < 2.0s（從 debug_trace `stage_timings` 量）
- prod smoke：`?debug_trace=true` 對 b21 query 看 envelope `rerank_applied=True / rerank_input_count=30`，且 tool latency < 2s

**In scope**：

- `voyage_rerank` 函式 + 整合 caller
- VOYAGE_API_KEY env var（backend / worker / dispatcher / beat 4 個 service 都設）
- voyageai SDK 進 requirements.txt
- 5 unit test + 6 整合 test
- Smoke + 8 題 subset eval + case study

**Out of scope**：

- b20 retrieval miss
- 其他 retrieval tool
- 多 show 通用化
- N 變動實驗（N=30 先驗證，N=50/100 留作未來）

## Risks / Trade-offs

- **Risk**：Voyage API 月成本估算 < $5 失準（譬如有 power user 跑大量 cross_episode query）→ Mitigation：envelope `rerank_input_count` 可監控、月底 audit log，必要時加 in-memory cache 或加 rate limit
- **Risk**：Voyage API 延遲 P99 比 P50 高很多（外部 API 常見）→ Mitigation：timeout 3.0s + fail-open，最壞 case 等於目前 baseline（無 rerank）
- **Risk**：Voyage 對特定中文 phrasing 排序判斷有偏（vs LLM-as-reranker 的優勢）→ Mitigation：8 題 subset eval 是直接判斷標準，metric 沒過就 revert
- **Risk**：voyageai SDK 升級 breaking change → Mitigation：pin version in requirements.txt
- **Trade-off**：每次 cross_episode query 多 ~150ms latency 換 chunk_recall 改善。如果 metric 沒過會 revert，並不會留下慢但無效的程式碼

## Migration Plan

1. Implement `voyage_rerank` + 改 caller + unit test（local）
2. backend/.env 加 `VOYAGE_API_KEY`；本地 pytest 跳過實際 API call（mock client）
3. Zeabur 4 service env 設 `VOYAGE_API_KEY`（按 memory `feedback_zeabur_variable_create_dumps_env.md` redirect stdout 避免印 key）
4. git push → Zeabur build → 等 RUNNING（per memory `feedback_zeabur_deploy_monitor_pattern.md`）
5. Smoke：prod debug_trace b21 看 envelope `rerank_applied=True` + tool latency < 2s
6. 跑 8 題 subset eval 對 baseline 0.244
7. Metric 達標 → archive；不達標 → revert commit + case study 寫 negative finding + 評估下個 lever（譬如 Cohere 或自架）

**Rollback**：revert 單一 commit 即可；voyage_rerank 是新增函式 + 一處 call site 改動，schema 不變。

## Open Questions

- Voyage API key 採購：user 是否已有帳號還是要新申請？採購流程獨立於本 change
- Voyage rerank-2.5 是否支援 async client：voyageai SDK 文件 0.4+ 應該有 `AsyncClient`，apply 階段要驗
- 是否要在 envelope 加 `rerank_provider: "voyage"` 額外欄位給未來 multi-provider 切換用？目前先不加，保持最小契約
