## Context

接 `retrieve-quality-step1-idf-and-prefilter` 2026-05-28 archive 失敗教訓：

**現役 eval pipeline 結構**（`backend/eval/`）：
- `judge_chat_v2.py`（183 LOC）— LLM judge prompt + invoke
- `runner_v2_aggregate.py`（109 LOC）— per-design_type aggregate + markdown report
- `graders/`（4 個 plugin × ~70-110 LOC）— count_consistency / chunk_recall_grouped / ordinal_resolution / answer_contradict_check
- `graders/loader.py`（50 LOC）— plugin discovery
- `metrics/judge_metrics.py` — DeepEval GEval wrap（retrieval bake-off 用，**chat eval 沒接**）
- `scripts/run_chat_agent_eval_v2.py` — runner CLI

**觀察盲點清單**（2026-05-28 RCA 拆出來）：
1. `agent_responses_meta` 只記 `tool_calls_n: int`，沒留 (tool_name, tool_args, tool_result_chunks, search_query)
2. LLM call 層完全沒留紀錄（messages / output / finish_reason / token usage 都沒存）
3. 沒 episode-scoped retrieval probe 工具，retrieval 改動 validation 容易 false positive
4. 沒 prompt → search query fingerprint diff，prompt 改動的 retrieval side effect 沒法事前抓
5. DeepEval 框架已部分裝（retrieval bake-off 用）但 chat eval 沒接，等於只用一半

## Goals / Non-Goals

**Goals**:

- Span-level trace 落地（per-LLM-round + per-tool-call + per-stage）寫 PG + Langfuse 雙 sink
- Langfuse UI 可即時看 trace tree / 跨 run 比對 / prompt versioning
- DeepEval extend 到 chat eval，補 Ragas 級 4 個 metric（Answer Relevancy / Contextual Precision / Faithfulness / Answer Similarity）
- 新增 episode-scoped retrieval probe CLI + prompt fingerprint diff CLI（兩個 retrieval / prompt PR 必跑工具）
- 既有 6 個自寫 grader + judge prompt 不動（calibrate 數據守住）
- 自寫 `context_entity_recall` grader（用 DeepEval GEval custom rubric）補最後一個 Ragas gap

**Non-Goals**:

- 不評估 latency / TTFT / TPS / token cost（後續再做，schema 預留欄位）
- 不裝 Ragas / Phoenix / OpenLLMetry（DeepEval + Langfuse 已 cover）
- 不重做既有自寫 grader / 不換 judge prompt
- 不做 trace UI 客製化（Langfuse 自帶 UI）
- 不卡 CI（probe / fingerprint diff 是 RCA 工具，PR 流程靠 reviewer 自律 + PR template 軟約定）

## Decisions

### Decision 1: Tracing 走 Langfuse **Cloud Free** + PG eval_traces 雙 sink

**選**：
- **Langfuse Cloud Free tier**（cloud.langfuse.com，2026-05-29 拍板，見 memory `project_langfuse_cloud_free_track_usage.md`），Python SDK `@observe` decorator 包 agent loop + tool dispatch + LLM call
- 同時自寫 `span_writer.py` hook 把 span tree 寫進 PG `eval_traces` table（見 Decision 1a 取捨）

**拒**：
- **Langfuse self-hosted on Zeabur**（原方案）→ Langfuse 官方無 production reference sizing；minimum 11 vCPU/25.5 GiB + ClickHouse ≥16 GiB；現 Linode SIN VPS `g6-standard-2`（2c/4G/80G）塞不下；升到能跑 prod-safe 自架要 `g6-standard-16` $192/月（+$180）。自架等於賭官方沒給的數字
- 只用 Langfuse 不寫 PG → 失去 SQL audit + MCP 即時查 + 跟 grader pipeline 對接 + Cloud Free 30 天後過期
- 只寫 PG 不用 Langfuse → 失去 trace tree UI + 跨 run diff + prompt versioning
- 自己刻 trace UI → 重複造輪子

**Rationale**:
- Langfuse 已成熟、UI 完整、Cloud Free 月費 $0、PodcastRAG trace 內容為公開 podcast 資料無 PII 隱私顧慮
- Free quota 50k units/月：估目前 dev ~8k units、Phase 1 dogfood ~35k 撐得住；撞 40k/100k/PII 任一條件再重啟自架評估
- PG 雙 sink 給「跟既有 grader / runner / MCP query 對接」的能力 — trace 資料當「first-class 資料」處理而非只給 UI 看
- 跨 run RCA query 走 SQL（譬如「找出所有 b18 失敗 case 的 search_query」），不卡 Cloud API rate limit + 不受 Cloud 30 天保留限制

### Decision 1a: PG `eval_traces` 雙寫 vs Cloud single source of truth — **選雙寫**

Cloud Free 拍板後重評估「PG `eval_traces` 表還要不要做」。

**選**：保留 PG eval_traces 雙寫（task 1.2 / 1.4 / 1.6 不砍）

**拒**：
- Cloud 為 single source of truth、砍掉 PG 表 → 三個破口：
  - (a) Cloud Free 只保留 30 天，超過就 query 不到歷史 baseline；自架資料庫永久保留
  - (b) 失去 MCP `podcastrag-pg` 即時 query 能力（譬如 RCA 時 `SELECT search_query FROM eval_traces WHERE item_id='b18'` 走 MCP 一秒回，走 Cloud API 要 export + 解析）
  - (c) 跟既有 grader / runner / eval result file 跨表 join 不了（result file 內 `meta.run_id` ↔ trace `run_id` 對齊靠 SQL）

**Rationale**:
- 雙寫成本低：`span_writer.write_span` 已是 fire-and-forget try/except，PG insert 跟 Cloud SDK upload 平行跑；P95 增量估 < 5ms（PG insert 走 asyncpg pool）
- PG 表本來就是 audit trail / 長期保留 / SQL-first RCA 的角色；Cloud 是 UI / 跨 run diff / prompt versioning 的角色
- 角色分工清楚，「砍 PG」省 ~50 LOC + 1 alembic migration 但失去長期 audit 能力，不划算
- 若未來 Cloud 撐不住升 Core 或自架，PG 表自然成為遷移時的「歷史資料保險」

### Decision 2: PG `eval_traces` 走 span 模型（OTel 風格）

**選**：表 schema 走 span 模型（不是 row=trace, column=tool）：

```sql
CREATE TABLE eval_traces (
  span_id UUID PRIMARY KEY,
  trace_id UUID NOT NULL,
  parent_span_id UUID NULL,
  run_id TEXT NOT NULL,              -- eval run identifier
  item_id TEXT NOT NULL,              -- golden set item (e.g. 'b18')
  turn_idx INT NOT NULL,
  span_type TEXT NOT NULL,            -- 'llm_call' / 'tool_call' / 'stage'
  span_name TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ NULL,
  elapsed_ms INT NULL,
  -- LLM call fields
  llm_model TEXT NULL,
  llm_finish_reason TEXT NULL,
  llm_prompt_tokens INT NULL,
  llm_completion_tokens INT NULL,
  llm_messages_json JSONB NULL,
  llm_output_text TEXT NULL,
  -- Tool call fields
  tool_name TEXT NULL,
  tool_args_json JSONB NULL,
  tool_result_chunks_json JSONB NULL,
  search_query TEXT NULL,             -- extracted from search_* tool args
  -- Stage timing
  stage_name TEXT NULL,
  -- Meta
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_eval_traces_run_item ON eval_traces (run_id, item_id);
CREATE INDEX ix_eval_traces_trace ON eval_traces (trace_id);
CREATE INDEX ix_eval_traces_search_query ON eval_traces (search_query) WHERE search_query IS NOT NULL;
```

一個 chat turn 跑完留下 N 個 span（agent loop 多 round × per-round tool calls + per-stage timing）。Span tree 由 `parent_span_id` 構成。

**Rationale**:
- OTel span 模型是業界標準（Langfuse 內部也用），雙 sink 對得齊
- 用 enum-style `span_type` + nullable 欄位涵蓋 LLM / Tool / Stage 三類，避免三張表 JOIN
- `search_query` 獨立 index 因為 prompt fingerprint diff 主要 query 路徑

### Decision 3: DeepEval 走 hybrid（4 個內建 + 1 個 GEval 自寫，保留 6 個自寫）

**選**：
- DeepEval **內建** 4 個 metric 接 chat eval：`AnswerRelevancyMetric` / `ContextualPrecisionMetric` / `FaithfulnessMetric` / `AnswerSimilarityMetric`
- DeepEval **GEval custom rubric** 1 個：`context_entity_recall`（DeepEval 沒內建版）
- 自寫保留 6 個：chunk_recall_grouped / count_consistency / ordinal_resolution / answer_contradict_check / refusal_appropriateness / pronoun_attribution_check

**拒**：
- 全 DeepEval（包括把 6 個自寫包成 DeepEval custom metric）→ 多 wrapper indirection、calibrate 數據作廢、跑 LLM call 走 DeepEval client 還要再 wrap AI Hub
- 不裝 DeepEval 全自寫 → 重複造輪子、自己維護 Ragas 級 metric 實作

**Rationale**:
- DeepEval 內建 metric 用 `OPENAI_API_KEY` env，跟我們既有 backend/.env（AI Hub key）相容
- 跟自寫 grader 共存：runner_v2_aggregate 接受 plugin grader 就行，DeepEval wrap 跟自寫 grader 同 interface
- 6 個自寫保留理由：podcast-specific（GT 結構 / multi-turn / refusal nuance），DeepEval 沒對應且 calibrate 過

### Decision 4: Episode-scoped retrieval probe CLI 獨立 script，不放 eval runner 內

**選**：新增 `backend/eval/scripts/retrieve_probe.py` 接 `--show_id --episode_id --query --top_k 50`，直接 import `app.services.rag.retrieve_hybrid` 跑、印 chunk ranking + GT 標註。

**拒**：
- 包進 eval runner 一起跑 → runner 已夠複雜、加 probe 邏輯混入 grader sample
- 散在 ad-hoc SQL → 每個 PR 重發明、false positive 風險回來

**Rationale**:
- 獨立 CLI 讓 retrieval PR reviewer 在 PR description 貼結果，類似 `EXPLAIN ANALYZE` 文化
- 跟 eval pipeline 解耦 — probe 是「sanity check 單一 query」不是「跑全 golden set」
- 後續可以擴 `--diff-rank-pre-after` flag 對比 two-version retrieval ranking

### Decision 5: Prompt fingerprint diff 走「calibration set 8 題 + trace SQL」

**選**：新增 `backend/eval/scripts/prompt_fingerprint_diff.py`：
1. 接 `--old-commit --new-commit --dataset backend/eval/datasets/_calibration_8.json`（新增 8 題 calibration set，從 extended-multi-turn-40 subset 挑 covering 各 design_type）
2. 對兩個 commit 各跑 chat eval（透過 nohup + 等回）→ trace 落 PG `eval_traces`
3. SQL query 抓兩 run 的 `search_query` per (item_id, turn_idx)
4. 印 markdown diff 表（item / turn / old_query / new_query / changed?）

**拒**：
- 全 34 題 calibration → 跑兩次 chat eval ~$10 + 30 分鐘等，PR 不會願意跑
- 不獨立 calibration set → 重用 full golden set 但太貴
- CI 卡 merge → 每個 prompt PR 都卡 $0.5 + 30 分鐘等 → reviewer 會繞過

**Rationale**:
- 8 題 calibration set 跑兩次 ~$2 + 5 分鐘，PR 願意跑
- 走 trace SQL 而非重 instrument → 唯一 source of truth
- 軟約定（PR template 提示 + reviewer 要求貼）優於硬 gate

### Decision 6: Cloud Free 用量追蹤 + 自架重評估觸發條件

**選**：上線後固定追蹤 cloud.langfuse.com → Settings → Usage 的月 units 用量，達任一條件觸發重新評估自架：

| 觸發條件 | 行動 |
|---|---|
| 月 units > 40k（80% Free quota） | 評估升 Langfuse Core $29/月 vs 自架 |
| 月 units > 100k（連 Core 都撞） | 強制重評估自架（升 Pro $199 或自架 VPS） |
| trace 內容開始含 PII / 客戶私人對話（譬如 Phase 2 全站登入後 user 真實 query） | 強制重評估自架（隱私不上 SaaS） |
| Langfuse Cloud 改價 / 改額度 | 重評估 |

每週固定一個時段對 dashboard 看 units 用量、記趨勢（dev / dogfood / A-B 各別貢獻多少）；同時校準目前的 ~10 units/trace 估算對不對。

**拒**：
- 不追蹤、撞牆才反應 → Cloud Free 撞牆會 silently drop traces，RCA 時才發現資料不全
- 一上線就先升 Core $29 「保險」 → 沒實際用量 evidence 浪費月費

**Rationale**:
- 「先用 Cloud Free、撞觸發點再評估」是「省 $180/月升 VPS + 賭官方沒給的 sizing 數字」的對立方
- PG eval_traces 雙寫（Decision 1a）保證即使 Cloud 撞 quota / 過期，主要 SQL audit 路徑不會掛
- 撞 (b)(c) 兩條件回頭自架時，本 change 累積的 PG eval_traces 資料可直接遷移當歷史 trace 起點

### Decision 7: span_writer hook 走 try/except 不阻擋 main path

**選**：`span_writer.write_span(span)` 內部 wrap try/except，DB 寫失敗 log warning 不 raise；agent loop / eval runner 不會因為 trace 寫失敗炸掉。

**Rationale**:
- Tracing 是「nice to have」不是「mission critical」，DB 抖一下不能影響 user query / eval run
- 失去 trace 的單一 case log 出來、後續 manual replay 即可

## Implementation Contract

**Behavior (observable)**:

- 每跑一次 chat agent query（含 `?debug_trace=true` 與否都跑）→ Langfuse Web UI 看得到對應 trace tree，含 LLM rounds + tool calls + stage timings
- PG `eval_traces` 同步寫入，run_id 跟 eval result file 對得齊（譬如 result file = `baseline-step1-foo-2026-05-XX-chat.json` 內 `meta.run_id` = trace `run_id` column）
- runner_v2_aggregate 跑完報告含 10 個 metric（既有 6 個 + 新 4 個 DeepEval + entity recall）
- `retrieve_probe.py --episode_id <X> --query <Y>` 印 top-50 chunks rank + 高亮 GT 位置
- `prompt_fingerprint_diff.py --old <SHA1> --new <SHA2>` 印 markdown diff 表

**Interface / data shape**:

- `eval_traces` PG table（schema 在 Decision 2）
- `backend/eval/tracing/langfuse_setup.py`：`init_langfuse() -> None` + `@observe` decorator export
- `backend/eval/tracing/span_writer.py`：`write_span(span_dict) -> None`（async-safe，PG dual-sink）
- 新 4 個 grader 走既有 plugin loader interface（`grade(item, response, judge_verdict) -> dict`）
- 兩個 CLI script 走 argparse + `__main__`

**Failure modes**:

- DB 寫 trace 失敗 → log warning + 不阻擋；用戶 query / eval run 照常完成
- Langfuse SDK 上傳失敗 → SDK 內建 retry + offline queue，不阻擋
- DeepEval LLM call 失敗 → grader 回 `{score: null, passed: false, details: {error: ...}}`，runner 照常 aggregate（既有行為一致）
- `eval_traces` table missing（migration 沒跑成功）→ span_writer log warning + skip 寫入，Langfuse 仍正常

**Acceptance criteria**:

1. 對任一 chat agent query 跑完，PG `eval_traces` 內可查到 ≥3 個 span（at least 1 LLM call + 1 tool call + 1 stage）；**Langfuse Cloud Web UI** 看得到等效 trace tree
2. 跑 chat baseline 全 34 題後，result file aggregate 含 10 個 metric（既有 6 + 新 4），無 null aggregate
3. `retrieve_probe.py` 對 b18 query + EP44 跑 → 印 top-50 chunks 含起始時間 + 哪些是 GT chunk
4. `prompt_fingerprint_diff.py` 對任一既有 2 commit 跑 → 印 8 題 calibration 的 search query diff 表
5. 跟 `feedback_idf_show_wide_failed_2026_05_28.md` 教訓對齊：retrieval PR 跑 probe + prompt PR 跑 fingerprint diff → 都能事前抓到 Layer A / Layer B 風格 side effect（dry-run 驗證在 task 中）
6. Phase 4 灰度測 prod chat user 流量 P95 latency 增量 < 100ms（含 Cloud SDK HTTP 往返）；若達標可考慮 default 開、不達標保持 eval run only + 寫 follow-up

**Scope boundaries**:

- 修改範圍鎖 `backend/eval/` 大半 + chat_agent 加 trace decorator + 新 alembic migration + 4 service env 加 Langfuse keys
- **不**動 Zeabur 部署架構（無新 service，純走 Cloud Free SaaS）
- **不**動 retrieval SQL / chunking / embedding / 既有 6 grader 邏輯 / judge prompt 內容
- **不**動 prod chat agent 對 user 行為（trace 是 side channel + env-gated，回應路徑不變）

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Cloud Free 撞 50k units 月上限 | 觸發 Decision 6 條件、評估升 Core $29 或自架；PG eval_traces 雙寫保證 SQL audit 路徑不受影響 |
| Cloud Free 30 天 retention 後過期 | PG eval_traces 雙寫永久保留為長期 audit + 跨月歷史 baseline 對比來源 |
| Cloud SDK 上傳燒 chat agent 主路徑 latency | `@observe` decorator 走 SDK 內建 async batch upload + offline queue；env flag `EVAL_TRACING_ENABLED` 預設 false，prod user 流量不開；估 Cloud SDK 額外 HTTP 往返 ~100ms（比自架本地 SDK 多） |
| Cloud 服務 outage / API rate limit | PG eval_traces 雙寫保證 RCA SQL 路徑不掛；Cloud 部分失去當下 trace UI 但不阻擋 eval run |
| `eval_traces` 表 row 量長期累積 | TTL policy（譬如 90 天 partition drop）後續加；首版不管 |
| DeepEval LLM call 燒額外 token | 4 個新 grader × 34 題 ≈ 136 LLM call/run × ~$0.01 = $1.36/run，可接受 |
| DeepEval LLM call 額外吃 Langfuse units | DeepEval 4 grader 不走 `@observe`、不上傳 Cloud；只 eval runner 主路徑進 trace |
| 新 grader 跑了發現結果跟自寫 grader 矛盾 | 共存比較期 — 兩個都跑、aggregate 都報、人 calibrate；不急切換 |
| Trace 雙 sink 寫入慢、影響 chat agent latency | `write_span` async + try/except + 失敗不 raise；測量 P95 增量 < 100ms（含 Cloud SDK HTTP 往返） |
| Langfuse Cloud Free 條款 / 計價變動 | Decision 6 觸發條件 (d)；屆時重評估自架或升 Core |
| 8 題 calibration set 代表性不夠 | 用 design_type 覆蓋（show_overview / guest_find / topic_find / date_find / deep_dive EP-ref / cross_episode / multi_turn / negative）每類至少 1 題 |

## Migration Plan

1. **Phase 1: Langfuse Cloud Free 接入 + PG tracing infra**
   - 1a: 申請 cloud.langfuse.com 帳號 + 建 project `podcastrag-eval` + 拿 `pk-lf-*` / `sk-lf-*` keys（走 `feedback_secret_handoff_via_file.md` SOP）
   - 1b: alembic migration 加 `eval_traces` table（per Decision 1a 雙寫保留）
   - 1c: `langfuse_setup.py`（SDK init + `@observe` re-export）+ `span_writer.py`（PG dual-sink）寫好、chat agent loop 加 `@observe`
   - 1d: 對一個 manual query 跑 → 驗證 Langfuse Cloud Web UI + PG eval_traces 都有 span

2. **Phase 2: DeepEval 4 個 metric 接 chat eval**
   - 2a: 4 個 grader wrapper 寫好（answer_relevancy / contextual_precision / answer_similarity / faithfulness_deepeval）
   - 2b: `context_entity_recall.py` 用 GEval custom rubric 自寫
   - 2c: `judge_chat_v2.py` 呼叫新 grader、`runner_v2_aggregate.py` aggregate
   - 2d: 對 8 題 calibration set 跑 → 驗證 10 個 metric 都非 null

3. **Phase 3: CLI 工具**
   - 3a: `retrieve_probe.py` 寫好 + 對 b18 EP44 跑驗證
   - 3b: `_calibration_8.json` 新建（從 extended-multi-turn-40 挑 8 題覆蓋 design_type）
   - 3c: `prompt_fingerprint_diff.py` 寫好 + 對既有 2 commit 跑驗證

4. **Phase 4: 結合與驗證**
   - 4a: 跑全 34 題 chat baseline 新 pipeline → 對比舊 baseline result（既有 6 metric 應該完全一致 ± 噪音）
   - 4b: dry-run 驗證 — 對 archived `step1-idf-and-prefilter` 兩個 commit 跑 `prompt_fingerprint_diff` → 應該抓到 Layer B 的 query 變化；對 b18 跑 `retrieve_probe` 帶 IDF-bucketed SQL vs legacy → 應該抓到 episode-scoped rank 差異
   - 4c: PR template 加 retrieval PR / prompt PR section 提示跑哪個工具

5. **Phase 5: Case study + memory**
   - 5a: case study 寫教訓 + workflow 指南
   - 5b: 既有 memory（IDF 失敗 / prompt 飽和）加 follow-up「現在有工具可抓」段
   - 5c: roadmap 更新「eval-framework 已完，下動可重啟 BM25 / EP-scoped IDF 等實驗」

## Open Questions

- Cloud Free 30 天 retention 是否夠用？目前判斷夠（PG eval_traces 雙寫做長期保留），撞觸發點再重評估
- 真實 unit 消耗對不對 ~10 units/trace 的估算？上線後第一週校準
- DeepEval Faithfulness vs 自寫 factual_correctness 該共存還是擇一？建議共存比較期 2-4 週後決定
- `_calibration_8.json` 8 題挑選 — 從 extended-multi-turn-40 哪 8 題最具代表性？首版直接挑 b01/b08/b14/b17/b18/b22/mt03/mt04（含 EP-ref / cross / multi-turn / negative）
- chat agent trace decorator 對 prod user 流量也要開？還是只 eval run 開？首版建議**eval run only**（env flag gate），prod 流量觀察 latency + Cloud units 用量後再決定
