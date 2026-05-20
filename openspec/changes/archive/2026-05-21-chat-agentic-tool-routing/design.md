## Context

本 change 接 `agentic-framework-bakeoff`（research spike，已完成 17/19 task，量化 + AI-delegate 質化雙重證據都收齊）的決策結果，把 prototype 升為 prod 級實作。

關鍵 carry-over 證據檔：
- `docs/case-studies/agentic-framework-bakeoff-2026-05.md` 「最終決策」段（拍板採用 A 原生 OpenAI tool calling）
- `backend/scripts/agentic_bakeoff/results/comparison.md` 跨指標比較表
- `docs/case-studies/framework-eval-perspective-shift-2026-05.md` 視角校準方法論（AI-delegate 視角為何強化 A 的勝差）

現況 chat pipeline 入口：`backend/app/api/query.py::query_show`（line 359），chat-mode 分支從 line 419 開始（payload.mode != "search" 即 chat）。流程：rewrite → embedding → entity 抽取 → metadata filter → `rag.retrieve_hybrid` → `_compute_enumeration_episodes` → LLM 答。

## Goals / Non-Goals

**Goals:**
- chat-mode 升為 agentic loop（agent 自己決定呼哪幾個 tool / 呼幾次）
- 修 bake-off 證實的 multi-turn carry 共通缺陷（L1 state 加 `last_enumeration_episodes`）
- Port-over：tool-eager prompt（降拒答 + 降幻覺）、strict Pydantic schema（input 驗證）
- 用 feature flag 安全 roll-out，eval 驗證通過才翻 default
- search-mode 完全不動（單一變因控制）

**Non-Goals:**
- 不做 L2 cross-session memory
- 不動前端 response shape（`landing-and-mode-orchestration-redesign` 處理）
- 不順手 split `rag.py`（獨立 change 處理）
- 不換 model（固定 AI Hub gemini-2.5-flash）

## Implementation Contract

### Module: `backend/app/services/chat_agent/`

**`agent.py::run_agent(question, session_id, show_id, db) -> ChatAgentResult`**
- 觀察行為：agent loop 跑完一輪對話、回傳 `ChatAgentResult(answer: str, tool_calls: list[ToolCallTrace], usage: TokenUsage, l1_state_after: ChatSessionState)`
- 失敗模式：tool dispatch 內部任何 exception 都被 `_dispatch_tool` 包成 `{"error": "<ExceptionClass>: <msg>"}` JSON 給 LLM；agent 仍嘗試完成回答（fail-soft），不上拋 5xx
- 迭代上限：max_iterations=10（沿用 bake-off 設定）；超過 → 回最後一輪 final answer + 標記 `truncated=true`
- 觀察 trace：每輪 tool dispatch 記進 `tool_calls` list（含 name / args / result_summary / raised / latency_ms）
- 驗證 target：`backend/tests/test_chat_agent_loop.py::test_run_agent_happy_path` 用 fixture 跑「歌單有哪幾集」→ assert tool_calls 含 `find_episodes_by_topic` + answer 非空

**`state.py::ChatSessionState`**
- Pydantic BaseModel 欄位：
  - `session_id: UUID`
  - `focused_episode_id: UUID | None`
  - `focused_episode_at: datetime | None`（用於 10 min idle 判斷）
  - `last_enumeration_episodes: list[UUID]`（最多保 20 個，FIFO 截斷）
  - `last_enumeration_at: datetime | None`（用於 10 min TTL 判斷）
  - `history_summary: str`（≤ 300 字）
  - `created_at: datetime`
  - `updated_at: datetime`
- 序列化：Redis 用 JSON string（key = `chat:session:{session_id}`，TTL = 2h，每次 write 都 refresh）
- 失效規則（讀時 lazy expire）：
  - `focused_episode_id` 若 `now - focused_episode_at > 10 min` → 讀出來時 set None
  - `last_enumeration_episodes` 若 `now - last_enumeration_at > 10 min` → 讀出來時 set `[]`
- 驗證 target：`test_chat_session_state.py::test_lazy_expire_focused_episode`、`test_lazy_expire_last_enumeration`

**`tools.py::TOOLS`**
- 11 個 callable 對應 9 個 tool 編號（沿用 bake-off `prototypes/a_native_openai/agent.py` 的 `_pydantic_to_openai_function` schema 自動產生機制）
- 所有 stub 換 real：
  - `get_episode_summary` → 接 `summary_pipeline` 既有 service
  - `get_episode_segments` → 接 `topic_segmentation` service
  - `search_within_episode` / `search_in_episodes` → 接 `rag.retrieve_hybrid` with `episode_id_filter`
  - `find_episode_by_ref` → 改接 `episode_finders.find_by_ref`（既有 / 或新加）
  - `get_show_overview` → 接 show DB query
  - `pin_episode` / `unpin_episode` → 寫 `ChatSessionState.focused_episode_id`
- `find_episodes_by_*` 三個 tool 內部呼完後**寫回 L1**：把結果 episode_ids 寫進 `state.last_enumeration_episodes`、updating `last_enumeration_at`
- 所有 tool input 用 Pydantic BaseModel（**strict schema port-over**）；validation fail 由 `_dispatch_tool` 抓 `ValidationError` 包成 error JSON 給 LLM

**`memory.py::build_messages(state, history, question) -> list[dict]`**
- L0：取最近 K=3 完整 message + 若有 `state.history_summary` 插 system 前；K=3 內訊息保留 tool call message round-trip
- L1 注入 system prompt：
  - `focused_episode_id`（若存在且未 expire）
  - `last_enumeration_episodes`（若存在且未 expire）+ 明文 instruction：「使用者說『第 N 集』請對應 last_enumeration_episodes[N-1] 的 ep_id；若 N 超出範圍，回拒答並請使用者澄清」
- `update_history_summary(state, last_turn)` → 用 gemini-2.5-flash-lite 增量壓縮，fail-open（壓縮失敗不擋主回答，state.history_summary 保留上一版）

**`prompts.py::SYSTEM_PROMPT`**
- 三段：
  1. 角色：「你是 PodcastRAG 的對話 agent，幫使用者查 podcast 內容」
  2. **Tool-eager instruction（port from E）**：「先呼 tool 找資料再決定。若使用者問特定資訊（集數 / 主持人 / 來賓 / 內容），**至少呼一個 tool 驗證**，不要憑印象拒答或 hallucinate」
  3. Grounded refusal：「若所有 tool 查完都沒找到，明確說『查不到 X』而不是編；若 schema invalid，請使用者澄清」

### Module: `backend/app/api/query.py`

- chat-mode 分支（line 419 起）加 flag 分流：
  ```python
  if settings.enable_agentic_chat:
      agent_result = await run_agent(...)
      return _agent_result_to_response(agent_result, quota_remaining)
  ```
- search-mode 完全不動
- 不刪 rule-based pipeline（flag = false 仍走它）

### Settings

`backend/app/core/settings.py` 加：
- `enable_agentic_chat: bool = False`（env `ENABLE_AGENTIC_CHAT`，default off）
- `agentic_chat_max_iterations: int = 10`
- `agentic_chat_l0_k_turns: int = 3`
- `agentic_chat_l1_ttl_seconds: int = 7200`
- `agentic_chat_focused_idle_seconds: int = 600`
- `agentic_chat_enumeration_ttl_seconds: int = 600`

### Schemas

`backend/app/schemas/query.py::ChatResponse` 加 optional：
- `tool_calls: list[ToolCallTrace] | None = None`
- `agent_truncated: bool = False`

回傳給前端時 flag=true 走 agentic 才填這兩個欄位；flag=false 維持既有 shape，前端不會壞。

## Decisions

### Decision: Feature flag 共存而不直接取代

**選擇**：rule-based pipeline 在 flag=false 時仍可走，不刪程式碼。

**理由**：
- bake-off A prototype 在 40 turn answer_keyword_hit 只有 0.32，prod 真實 query 不一定更好；風險控制
- 翻 default 前先用 staging eval + prod canary 驗證
- 若新 agent 在某類 query 慘輸 rule-based，可以快速回退

**替代**：直接取代 + 用 git revert 回退 — 風險過大，特別是已知 8/40 拒答問題

### Decision: 不純把 bake-off prototype 移過來

**選擇**：以 bake-off 的 `prototypes/a_native_openai/agent.py` (213 LOC) 為「結構參考」，重寫成 prod 級實作，**不再受 < 250 LOC 限制**。

**理由**：
- bake-off 限 250 LOC 是為了控制變因、強迫聚焦 framework ergonomics
- prod 級實作需要：error handling / retry / log / metric / circuit breaker hook / ai_steps usage 紀錄等，250 LOC 塞不下
- 但結構（agent loop / `_dispatch_tool` / `_pydantic_to_openai_function`）直接沿用

**替代**：原樣搬 → 缺 prod 級防護，prod 出事時無法 debug / 無 telemetry

### Decision: L1 state 用 Redis 不用 DB

**選擇**：`ChatSessionState` 存 Redis（既有 broker 連線），不存 Postgres。

**理由**：
- session-scoped 資料、TTL 2h，不需要長期保存
- 寫頻率高（每輪都更新 `last_enumeration_episodes` / `focused_episode_id`），Redis 寫速優於 PG
- 既有 Redis 已有 broker / cache / circuit breaker 多種用途，再加 chat session 不增 infra cost
- 失敗模式可接受：Redis 掛 → session state 重置 → user 體感 = 「對話歷史短暫消失」，不掉資料

**替代**：PG with TTL job → 多一個 dispatcher tick + 寫速慢 + cleanup 麻煩

### Decision: Tool-eager prompt 寫在 SYSTEM_PROMPT 不寫在 tool description

**選擇**：「先呼 tool 再決定」這 instruction 放 SYSTEM_PROMPT 第二段。

**理由**：
- system prompt 對 gemini-2.5-flash 的 instruction-following 較強
- 寫在 tool description 會被每個 tool 重複（11 個 callable × 一句話 = 雜訊）

**替代**：tool description 各自寫 → noise + 易 drift

### Decision: Multi-turn carry 用 ordinal-aware system prompt instruction

**選擇**：`build_messages` 把 `last_enumeration_episodes` 列在 system message，明文教 LLM「『第 N 集』= list[N-1]」。

**理由（從 bake-off 三 framework 全 fail 推導）**：
- bake-off 證實單純 framework 換不修這個缺陷
- 加 tool（`resolve_ordinal_reference(n)`）增加一輪 round-trip latency + cost
- 直接在 system prompt 教是最低成本最高回報

**替代**：
- (1) 純靠 enumerate 時用「1. EP142 2. EP134...」格式 — bake-off 沒測過、靠 LLM 自律不穩
- (3) 新 `resolve_ordinal_reference` tool — 多一輪 + cost

**驗證 target**：`test_chat_agent_multi_turn.py::test_enumeration_then_ordinal_reference` — 用 fixture 跑「歌單有哪幾集？」→「第三集是什麼內容？」，assert 第二輪呼到的 tool 是 `get_episode_summary(episode_id=last_enumeration_episodes[2])`

### Decision: Eval gate 在 roll-out 前

**選擇**：本 change archive 前必須跑既有 golden set eval（`backend/eval/datasets/this-not-that-cool.json`）對 agentic loop vs rule-based 對比，且不低於以下 gate：
- Recall@5 不降 > 5pp
- Faithfulness 不降 > 0.05
- answer_match 不降 > 5pp

**理由**：避免「改架構爽到、實際 user 體驗變差」

**替代**：直接 ship + 看 prod usage data → 太晚發現

## Risks

- **gemini-2.5-flash 拒答傾向強（bake-off 觀察 8/40 0 tool call）**：tool-eager prompt 可能改善但無 100% 保證。Mitigation：eval gate 卡 answer_match 不降 > 5pp
- **L1 state Redis 撞 broker 流量**：可接受（Redis 4GB Linode，broker 用量低）；若日後撞上，independent Redis instance 是後續優化
- **Token cost 上升**：bake-off A 跑 40 turn $0.0147；prod 預估每 query 比 rule-based 多 2-3 tool call round-trip ≈ 多 $0.0001-0.0002/query。月用量增加 < $10，可接受
- **flag rollback 不夠快**：env 改 + redeploy ≈ 2-3 min。Mitigation：admin UI 加 toggle（low priority follow-up）

## Migration Plan

1. **Phase 0**（本 change 範圍）：開發 + unit test + eval pass（gate 標準見上）+ archive
2. **Phase 1**（後續）：勾 `ENABLE_AGENTIC_CHAT=true` 在 staging / 自己 dogfood 兩週
3. **Phase 2**（後續）：翻 default = true、刪 rule-based pipeline（獨立 cleanup change）

無 DB migration、無 data migration。
