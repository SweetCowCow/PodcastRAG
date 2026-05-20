## 1. Settings + Response schema

- [x] 1.1 在 `backend/app/core/settings.py` 加 6 個 setting：`enable_agentic_chat: bool=False`（env `ENABLE_AGENTIC_CHAT`）/ `agentic_chat_max_iterations: int=10` / `agentic_chat_l0_k_turns: int=3` / `agentic_chat_l1_ttl_seconds: int=7200` / `agentic_chat_focused_idle_seconds: int=600` / `agentic_chat_enumeration_ttl_seconds: int=600`（落實 design.md "Settings" 段；Decision: feature flag 共存而不直接取代）
- [x] 1.2 在 `backend/app/schemas/query.py` 加 `ToolCallTrace` Pydantic model + `ChatResponse.tool_calls: list[ToolCallTrace] | None = None` + `ChatResponse.agent_truncated: bool = False`，flag=false 路徑回傳 None / False（落實 Requirement: Agent response schema exposes optional tool-call trace）

## 2. ChatSessionState + Redis 持久層

- [x] 2.1 在 `backend/app/services/chat_agent/state.py` 寫 `ChatSessionState` Pydantic BaseModel（8 個欄位 session_id / focused_episode_id / focused_episode_at / last_enumeration_episodes / last_enumeration_at / history_summary / created_at / updated_at，所有 datetime 用 UTC）。`last_enumeration_episodes` 寫入時 FIFO 截斷到 20 entry（落實 Requirement: ChatSessionState models per-session conversational anchors）
- [x] 2.2 在 `state.py` 寫 `ChatSessionStateStore` 類（load/save/delete）— Redis JSON 持久化、key `chat:session:{session_id}`、每次寫刷新 TTL = `agentic_chat_l1_ttl_seconds`、missing key 回 None 不 auto-create（落實 Requirement: Redis persistence with 2h TTL and refresh-on-write；design Module: `backend/app/services/chat_agent/`；Decision: L1 state 用 Redis 不用 DB）
- [x] 2.3 在 `ChatSessionStateStore.load` 加 lazy expiry：load 時 `focused_episode_at` 超過 10 min → 把 `focused_episode_id` / `focused_episode_at` 都設 None；`last_enumeration_at` 超過 10 min → `last_enumeration_episodes=[]` / `last_enumeration_at=None`；lazy expiry 不 write back（落實 Requirement: Lazy expiry of focused episode and enumeration anchors）
- [x] 2.4 在 `backend/tests/test_chat_session_state.py` 寫 5 個測試：`test_round_trip_save_load` / `test_ttl_refresh_on_write` / `test_lazy_expire_focused_episode_after_11min` / `test_lazy_expire_last_enumeration_after_11min` / `test_enumeration_fifo_truncation_at_20`。用 `fakeredis`

## 3. Memory + Prompts

- [x] 3.1 在 `backend/app/services/chat_agent/memory.py` 寫 `build_messages(state, history, question) -> list[dict]`：L0 取最近 K=3 完整 message（保留 tool call message round-trip）+ 若 `state.history_summary` 非空就插 system message 前；L1 注 system prompt 含 `focused_episode_id`（若未 expire）/ `last_enumeration_episodes`（若未 expire）+ 明文 ordinal instruction（落實 Requirement: System prompt injects active anchors with ordinal instruction；Decision: Multi-turn carry 用 ordinal-aware system prompt instruction）
- [x] 3.2 在 `backend/app/services/chat_agent/prompts.py` 寫 `SYSTEM_PROMPT` 三段（角色 / tool-eager / grounded refusal），第二段為 bake-off port-over from prototype E（落實 Requirement: System prompt instructs tool-eager grounded behaviour；Decision: Tool-eager prompt 寫在 SYSTEM_PROMPT 不寫在 tool description）
- [x] 3.3 在 `memory.py` 寫 `update_history_summary(state, last_turn)`：用 `summary` AI step config + gemini-2.5-flash-lite 增量壓縮到 ≤ 300 字；任何 exception 都 log + 保留舊 `history_summary`（fail-open）。寫對應測試 `test_summary_failure_fail_open_keeps_previous`（落實 Requirement: history_summary updated incrementally with fail-open semantics）

## 4. Tools 統一 schema + real wiring

- [x] 4.1 在 `backend/app/services/chat_agent/tools.py` 把 bake-off `backend/scripts/agentic_bakeoff/tools/` 的 11 callable 搬過來 + 6 個 stub 換 real wiring（`get_episode_summary` → `summary_pipeline`、`get_episode_segments` → `topic_segmentation`、`search_within_episode` / `search_in_episodes` → `rag.retrieve_hybrid` with filter、`find_episode_by_ref` → `episode_finders.find_by_ref`、`get_show_overview` → show DB query、`pin_episode` / `unpin_episode` → 寫 state.focused_episode_id）。沿用 bake-off 的 `_pydantic_to_openai_function` schema 自動產生；每 tool input 用 Pydantic BaseModel（strict schema port-over from B；Decision: 不純把 bake-off prototype 移過來；落實 Requirement: Tool registry exposes eleven callables backed by real services）
- [x] 4.2 在 `tools.py::_dispatch_tool` 加 (a) `ValidationError` → `{"error": "ValidationError: ..."}` JSON / (b) 其他 Exception → `{"error": "<class>: <msg>"}` JSON / (c) `find_episodes_by_guest` / `find_episodes_by_topic` / `find_episodes_by_date` 三 tool 呼完後寫回 `state.last_enumeration_episodes` + update `last_enumeration_at` 並 persist（design Module: `backend/app/services/chat_agent/`）

## 5. Agent loop

- [x] 5.1 在 `backend/app/services/chat_agent/agent.py` 寫 `run_agent(question, session_id, show_id, db) -> ChatAgentResult`：原生 OpenAI tool calling loop（拿 `answer` step config 的 base_url + api_key）+ `max_iterations` 從 settings + 每輪 tool dispatch 記 `tool_calls` trace + 達 max_iterations 回 `agent_truncated=true`；tool exception 永遠 catch 不丟 5xx（落實 Requirement: Agent loop drives chat-mode queries when feature flag is enabled）
- [x] 5.2 在 `backend/tests/test_chat_agent_loop.py` 寫 3 個測試：`test_run_agent_happy_path_enumeration`（fixture 跑「歌單有哪幾集」assert find_episodes_by_topic 被呼 + answer 非空）/ `test_tool_exception_caught_not_5xx`（mock tool raise → assert response not 5xx + tool_calls 有 raised 欄位）/ `test_iteration_cap_truncates`（mock LLM 不斷 emit tool call → assert agent_truncated=true）

## 6. 接進 query_show

- [x] 6.1 Chat-mode dispatches to agent loop when feature flag is enabled — 在 `backend/app/api/query.py::query_show` chat-mode 分支（line 419 起 `if payload.mode == "search"` 後的 else block）最前面加 flag 分流：
      ```python
      if settings.enable_agentic_chat:
          agent_result = await run_agent(payload.question, payload.session_id, show_id, db)
          return _agent_result_to_response(agent_result, quota_remaining)
      ```
      寫 `_agent_result_to_response` helper；search-mode 分支不動（design Module: `backend/app/api/query.py`；落實 Requirement: Chat-mode dispatches to agent loop when feature flag is enabled）
- [x] 6.2 確認 quota 在 dispatch 之前已 atomic decrement、agent / rule-based 兩條路徑表現一致（既有 `_atomic_decrement_quota` 已在 chat-mode 入口執行；本 task 只寫 assertion test `test_quota_decrement_uniform_across_pipelines` 驗證兩條路徑都 decrement 一次）（落實 Requirement: Quota accounting applies uniformly across both pipelines）

## 7. Multi-turn carry + Eval gate prep

- [x] 7.1 在 `backend/tests/test_chat_agent_multi_turn.py` 寫 `test_enumeration_then_ordinal_reference`：跑「歌單有哪幾集？」（assert `find_episodes_by_topic` 被呼、L1 state `last_enumeration_episodes` 寫入）+「第三集是什麼內容？」（assert 第二輪呼到的 tool 是 `get_episode_summary(episode_id=last_enumeration[2])`，NOT `find_episode_by_ref(ref="EP3")`）。這題是 bake-off 三 framework 全 fail 的 regression test
- [x] 7.2 寫 `backend/scripts/run_chat_agent_eval.py`：對 `backend/eval/datasets/this-not-that-cool.json` 跑兩次（flag=false rule-based + flag=true agentic），記 Recall@5 / Faithfulness / answer_match，輸出對比表 + 寫進 `docs/case-studies/agentic-chat-eval-2026-05.md`。Gate：agent 比 rule-based Recall@5 不降 > 5pp、Faithfulness 不降 > 0.05、answer_match 不降 > 5pp。Gate fail → case study 寫 fail 原因 + 不翻 default（落實 Requirement: Eval gate blocks rollout of agentic chat default；Decision: Eval gate 在 roll-out 前）
