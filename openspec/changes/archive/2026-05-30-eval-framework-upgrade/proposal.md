## Summary

把現有 chat agent eval pipeline 升級成「span-level observability + 框架輔助 + episode-scoped probe + prompt fingerprint diff」的下一代基礎，解掉 2026-05-28 `retrieve-quality-step1-idf-and-prefilter` 失敗暴露的 RCA 工具盲點。

## Motivation

2026-05-28 `retrieve-quality-step1-idf-and-prefilter` 兩 Layer 全失敗 archive，case study 揭露三條 root cause 都跟 **eval observability 不足** 有關：

1. **Layer A failed**：show-wide DB probe 顯示 GT chunk #1 → 推進 chat eval → chunk_recall 0.482 → 0.382。RCA 才發現 show-wide pool（10K+ chunks）跟 chat agent 實際呼叫的 episode-scoped pool（~30 chunks）ranking 行為完全不同。**沒有 episode-scoped probe 工具，所以 false positive 沒被擋下**。
2. **Layer B failed**：原以為「pure prompt nudge, zero retrieval risk」→ chunk_recall 0.482 → 0.340。RCA 才發現新 prompt 段改了 agent 對同一 question 措辭 `search_*(query: str)` 的 query 字串 → 下游 ts_rank 收到不同 token → 不同 GT 命中。**沒有 prompt → query fingerprint diff 工具，所以 prompt 改動的 retrieval side effect 沒被預測到**。
3. **RCA 階段觀察工具不足**：現役 eval result 只記錄 `tool_calls_n`（一個整數），沒留 (tool_name, tool_args, tool_result_chunks, search_query) per turn，要復現失敗 case 內部行為只能憑邏輯推測 + 重跑單題。**沒有 per-question tool-call trace，每次 RCA 都得從頭挖**。

User 也明確 push：要細到 LLM round（per-round messages + finish_reason + output_text），現在「看的太粗、沒進到 LLM 細看，所以都改不好」。

## Proposed Solution

### Layer 1: Tracing 基礎（Langfuse **Cloud Free** + PG eval_traces 表雙寫）

- **Langfuse Cloud Free tier**（cloud.langfuse.com）— 不自架。2026-05-29 拍板（見 memory `project_langfuse_cloud_free_track_usage.md`）：Langfuse 官方無 production reference sizing，minimum 11 vCPU/25.5 GiB + ClickHouse ≥16 GiB；現 Linode SIN `g6-standard-2`（2c/4G）塞不下，自架要升 VPS +$180/月；Cloud Free 50k units/月 + 30 天保留 + 含 LLM-as-judge，估目前 ~8k units / Phase 1 dogfood ~35k 撐得住。
- Python SDK `@observe` decorator 包 chat agent loop + tool dispatch + LLM call → trace span 自動上傳 Langfuse Cloud
- 同時自寫 hook 把 span 寫一份到 PG `eval_traces` table（schema 含 span_type / parent_span_id / llm_messages_json / llm_output_text / llm_finish_reason / tool_args_json / tool_result_chunks_json / search_query / elapsed_ms / token_usage）
- 雙寫理由：Cloud Free 給 UI / 跨 run 比對 / 30 天保留；PG 給 SQL audit + 跟 MCP query 整合 + 跟既有 eval pipeline 結合 + 不依賴 Cloud 可用性 + 長期保留（Cloud Free 30 天後過期）
- **自架重評估觸發條件**：月 Cloud units > 40k（80% Free quota）/ > 100k（連 Core $29 都撞）/ trace 出現 PII / Cloud 改價

### Layer 2: DeepEval extend 到 chat eval（接 4 個 Ragas 級指標）

- 既有 `judge_metrics.py` 已 wrap DeepEval `GEval`（retrieval bake-off 用），extend 到 chat eval 路徑
- 加 4 個 DeepEval 內建 metric 接 chat eval：`AnswerRelevancyMetric` / `ContextualPrecisionMetric` / `FaithfulnessMetric` / `AnswerSimilarityMetric`
- 既有 6 個自寫 grader 全部保留不動：chunk_recall_grouped / count_consistency / ordinal_resolution / answer_contradict_check / refusal_appropriateness / pronoun_attribution_check（podcast-specific，DeepEval 沒對應）
- Context Entity Recall 用 DeepEval GEval custom rubric 自寫

### Layer 3: Episode-scoped retrieval probe CLI

- 新增 `backend/eval/scripts/retrieve_probe.py` — 接 `--show_id --episode_id --query --top_k 50` 跑 `retrieve_hybrid(episode_id_filter=[ep_id])` + 印 chunk ranking + GT 位置
- 用途：retrieval 改動 PR 必跑、結果貼進 PR description、避免 show-wide probe false positive

### Layer 4: Prompt change fingerprint diff CLI

- 新增 `backend/eval/scripts/prompt_fingerprint_diff.py` — 接兩個 commit SHA，對固定 8 題 calibration set 跑兩版 prompt + 從 trace 抓 agent 生成的 `search_*(query)` 字面 → 印 markdown diff 表
- 用途：prompt change PR 必跑 + 貼結果、避免 Layer B 級 prompt → retrieval side effect 再撞

## Non-Goals

- **不**評估 latency / TTFT / TPS（後續再做，schema 預留欄位）
- **不**評估 token cost（同上，schema 預留）
- **不**裝 Ragas / Arize Phoenix / OpenLLMetry（DeepEval 已 cover Ragas 6 個指標，Phoenix / OpenLLMetry 跟 Langfuse 功能重疊）
- **不**重做既有 6 個自寫 grader（calibrate 數據可貴）
- **不**換 LLM judge prompt（`judge_chat_v2.py` 既有 prompt 不動）
- **不**做 trace UI 客製化（Langfuse 自帶 UI 直接用）
- **不**做 CI gate 卡 merge（fingerprint diff / probe 是 RCA 工具，PR 流程靠 reviewer 自律 + PR template 軟約定）

## Alternatives Considered

- **全 DeepEval 取代自寫 grader**：DeepEval 沒對應 chunk_recall_grouped（must/either/acceptable 三層 GT）/ count_consistency / ordinal_resolution / pronoun_attribution_check 等 6 個 podcast-specific 指標，硬塞要包成 DeepEval custom metric 反而多 wrapper indirection，calibrate 數據作廢。**Hybrid（DeepEval 接 4 個 + 自寫保留 6 個）省 300-450 LOC**
- **Ragas 整框架接入**：Ragas 是 framework not metric library，會把 judge prompt / API client / dataset format 全換掉，跟既有 stable judge_chat_v2 衝突。DeepEval 已有 6 個 Ragas 級 metric，覆蓋率夠
- **Langfuse self-hosted on Zeabur**（原方案，已拒）：Langfuse 官方 minimum 11 vCPU/25.5 GiB + ClickHouse ≥16 GiB；現 Linode SIN VPS 2c/4G 塞不下，升到能跑 prod-safe 的 `g6-standard-16` 月費 +$180。Cloud Free 月費 $0、PodcastRAG trace 內容為公開 podcast 資料無 PII 隱私顧慮，自架等於賭官方沒給的 sizing 數字
- **只用 Langfuse 不寫 PG eval_traces**：失去 SQL audit + MCP query 即時整合 + 跟既有 eval grader pipeline 對接的能力
- **只寫 PG eval_traces 不用 Langfuse**：失去 trace tree UI + 跨 run diff UI + prompt versioning，每次 RCA 都得手寫 SQL

## Impact

- Affected specs:
  - Modified: `rag-eval-runner`（trace persistence + DeepEval extend + probe / fingerprint CLI hooks）
  - Modified: `rag-eval-judge`（DeepEval metric 整合 4 個 + GEval entity recall）
  - Modified: `rag-eval-dataset`（calibration set 用於 prompt fingerprint diff）
  - New: `eval-observability`（Langfuse tracing + PG eval_traces table schema + span hierarchy contract）
- Affected code:
  - New: alembic migration 加 `eval_traces` table
  - New: `backend/eval/tracing/langfuse_setup.py`（SDK init + @observe wrapper）
  - New: `backend/eval/tracing/span_writer.py`（PG dual-sink hook）
  - New: `backend/eval/scripts/retrieve_probe.py`
  - New: `backend/eval/scripts/prompt_fingerprint_diff.py`
  - New: `backend/eval/graders/answer_relevancy.py`（DeepEval wrapper）
  - New: `backend/eval/graders/contextual_precision.py`（DeepEval wrapper）
  - New: `backend/eval/graders/answer_similarity.py`（DeepEval wrapper）
  - New: `backend/eval/graders/context_entity_recall.py`（DeepEval GEval wrapper）
  - Modified: `backend/eval/judge_chat_v2.py`（呼叫新 grader + 寫 trace）
  - Modified: `backend/eval/runner_v2_aggregate.py`（aggregate 加新指標）
  - Modified: `backend/eval/graders/loader.py`（plugin discover 加新 4 個）
  - Modified: `backend/app/services/chat_agent/agent.py`（加 @observe decorator）
  - Modified: `backend/app/services/chat_agent/tools.py`（tool dispatch trace + search_query capture）
  - Modified: `backend/requirements-eval.txt`（langfuse 加進去）
- Affected ops:
  - **無新 Zeabur service**（改走 Langfuse Cloud Free，2026-05-29 拍板）
  - 申請 cloud.langfuse.com 帳號 + 建 project + 拿 `pk-lf-*` / `sk-lf-*` keys（走 `feedback_secret_handoff_via_file.md` SOP，secret 走檔不走 chat）
  - 4 個 backend service（backend / worker / dispatcher / beat）加 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST=https://cloud.langfuse.com` env
  - 既有 `eval_traces` table 走 alembic 既有 backfill 模式（empty 啟動，eval run 時填充）
  - 設定每週對 cloud.langfuse.com → Settings → Usage 看月 units 用量、追蹤趨勢；撞 40k / 100k / 出現 PII 任一條件 → 重啟自架評估
- Affected docs:
  - `docs/research/eval-framework-upgrade-plan-2026-05-28.md`（規劃文件，不入 commit per 慣例）
  - 簡報 deck（QA 用 jpg/pdf 跑完即刪 per memory）
