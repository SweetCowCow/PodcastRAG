## Problem

Agentic chat 在某些 cross-episode 推論題（譬如 multi-turn-40 b20「節目裡迪拉怎麼描述中老年人的開工想法跟年輕時的差異」）對 prod 跑時直接回 HTTP 500：

```
openai.BadRequestError: Error code: 400 -
litellm.ContextWindowExceededError: This model's maximum context length is
128000 tokens. However, your messages resulted in 209751 tokens
(209082 in the messages, 669 in the functions). model=gpt-4o.
```

User 直接看到 5xx，違反 `chat-tool-error-isolation` archive 設定的「tool / 平台錯誤都應翻譯成 user-friendly 文字」原則。同題重跑時偶爾 HTTP 200，說明跟 agent loop 在多輪 tool round-trip 累積 messages 不 truncate 有關。

## Root Cause

1. **Tool result 不截斷**：`_dispatch_tool` 把每個 tool（譬如 `search_across_episodes`、`get_episode_segments`）回的整段 JSON 原文 push 進 `messages`。`get_episode_segments` 對 80-min episode 可回 3000+ segment dict（含 text），加上多輪 search 結果，累積 200K+ tokens 容易爆。
2. **無 per-round token budget guard**：agent loop 進下一輪前不檢查 `messages` 累計 token 數；一爆就直接 raise。
3. **LLM-side exception 沒被 envelope 接住**：`chat-tool-error-isolation` archive 的 `_classify_exception` + `Tool error envelope` 只包 `_dispatch_tool` 內部的 SQL / runtime exception，沒包 `client.chat.completions.create` 自己 raise 的 `openai.BadRequestError`；那層 exception 透到 endpoint handler → HTTP 5xx。

## Proposed Solution

1. **Per-tool-result truncate**（`_dispatch_tool` 包裝）：tool 回的 `result_str` 若超 `agentic_tool_result_max_chars`（settings 新欄位，預設 8000 chars ≈ 2K tokens）即截斷，尾註 `... (truncated, X chars omitted)`。`ToolCallTrace.result_full` 保留全長供 admin debug_trace。
2. **Per-round token budget guard**（agent loop 每輪 LLM call 前）：用 tiktoken 對 gpt-4o 編碼估算 `messages` 累計 token；若超 `agentic_chat_messages_max_tokens`（settings 新欄位，預設 100000，留 28K headroom for response + functions）則：
   - 從前面數移除最舊 tool result message（保留 system + 最近 N 輪 user/assistant 對）
   - 若一輪移除後仍超 budget → 在 messages 結尾加一條 system note「Context truncated by budget guard. Wrap up with current info.」並中止繼續 round，把 LLM 最近一條 message 當答案回傳；標 `agent_truncated=true`。
3. **LLM exception envelope**：agent loop 包 try/except 捕捉 `openai.BadRequestError`（含 `ContextWindowExceededError`），延伸 `_classify_exception` 加 `kind="context_exceeded"`；不讓 5xx 噴給 user，改回 `user_hint`「這題涉及內容太多，我只能列出部分結果。試試把問題拆小（譬如指定單一集數）」並結束 agent loop。
4. **Unit test**：truncate 行為（兩種 tool）、guard 觸發移除最舊 message、guard 第二輪仍超即中止、context-exceeded envelope 攔截 LLM 4xx、`agent_truncated=true` 標記。
5. **Prod smoke**：對 b20 那題 nohup 連跑 5 次，全部 HTTP 200 + answer 文字不含「技術問題 / 系統錯誤」。

## Non-Goals

- 不換 LLM model（升 gpt-5 / claude opus 改善 context 等屬 `agentic-model-tiering` follow-up）
- 不改 multi-tool 並行架構（latency p95 19s 改善屬 `agentic-model-tiering` follow-up）
- 不限縮 11 callable tool（功能完整保留）
- 不改 tool 內部 SQL（譬如 `_get_episode_segments` 不加 LIMIT；如果 truncate 是因為 tool 回過量、視 follow-up 處理）
- 不改 LLM judge / eval gate 機制

## Success Criteria

- 對 prod 用 backdoor session 跑 multi-turn-40 b20 一題 nohup 連 5 次，全部 HTTP 200 + answer 文字不含「技術問題 / 系統錯誤 / 資料存取」字串
- 跑同 multi-turn-40 dataset 一輪，empty-answer turns 從 1/40（baseline）→ 0/40
- 既有 `test_chat_agent_loop.py` / `test_chat_agent_multi_turn.py` / `test_chat_agent_telemetry.py` / `test_chat_tool_error_isolation.py` / `test_agent_result_mapper.py` 全綠
- 新增至少 4 個 unit test 涵蓋 truncate / guard / context-exceeded envelope / agent_truncated 標記

## Impact

- Affected specs: `chat-agentic-routing`（MODIFIED — 新增 token budget guard / tool result truncate / LLM-side envelope 三條 requirement）
- Affected code:
  - Modified:
    - backend/app/services/chat_agent/agent.py（per-round token guard + LLM exception 包裝）
    - backend/app/services/chat_agent/tools.py（`_dispatch_tool` result truncate）
    - backend/app/core/config.py（兩個 settings 新欄位）
  - New:
    - backend/tests/test_agent_token_budget.py（4-5 個 unit test）
  - Removed:
    - 無
