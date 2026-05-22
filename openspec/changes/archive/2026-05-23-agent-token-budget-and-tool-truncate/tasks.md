## 1. Settings 欄位

- [x] 1.1 在 `backend/app/core/config.py` 新增 `agentic_tool_result_max_chars: int = 8000`（per-tool LLM-facing truncate threshold）+ `agentic_chat_messages_max_tokens: int = 100000`（per-round token budget），與既有 agentic 欄位放一起，註解寫明用途與預設值來源（128K context - 28K headroom for response + functions = 100K budget）。

## 2. Per-tool-result truncate（spec: Tool dispatch SHALL truncate result strings sent to the LLM）

- [x] 2.0 實作 spec requirement「Tool dispatch SHALL truncate result strings sent to the LLM」。
- [x] 2.1 在 `_dispatch_tool` 或 caller 端把 `result_str = json.dumps(result_dict, ensure_ascii=False)` 之後新增 `truncated_str = _truncate_for_llm(result_str, settings.agentic_tool_result_max_chars)` helper（檔案：`backend/app/services/chat_agent/tools.py` 或 `agent.py`，取較自然位置），實作：若 `len(s) > cap` 則回 `s[:cap] + f"... (truncated, {len(s) - cap} chars omitted)"`；否則原樣回。
- [x] 2.2 把 messages.append 的 `content` 改成 `truncated_str`；`ToolCallTrace.result_summary` 也用 `truncated_str[:500]`；`ToolCallTrace.result_full` 仍存原始 `result_str` 不截。

## 3. Per-round token budget guard（spec: Agent loop SHALL guard per-round token budget before each LLM call）

- [x] 3.0 實作 spec requirement「Agent loop SHALL guard per-round token budget before each LLM call」。
- [x] 3.1 在 `agent.py` 新增 `_estimate_messages_tokens(messages) -> int` helper：try `import tiktoken; enc=tiktoken.encoding_for_model("gpt-4o")` → 對每 message `enc.encode(json.dumps(m))` 加總；fall back（ImportError 或 encoder 找不到）回 `sum(len(json.dumps(m)) for m in messages) // 4`。
- [x] 3.2 在 `run_agent` 主迴圈每個 `chat.completions.create` call **前**，呼 `_estimate_messages_tokens(messages)` 估算；若 > `settings.agentic_chat_messages_max_tokens`，進 `_apply_budget_guard(messages, budget)`：迴圈移除最舊的 `role=="tool"` message（保護 system + 最後 1 對 user/assistant），每次移除後重估，直到 ≤ budget 或無 tool message 可移。
- [x] 3.3 若 `_apply_budget_guard` 結束後仍 > budget：append `{"role":"system","content":"Context truncated by budget guard. Wrap up with the information you already have."}` → `break` out of 迴圈 → 用最後一條 assistant message（或 "" 若無）當 `answer` → `agent_truncated=True`。
- [x] 3.4 把 budget guard 結果（移除幾條 tool message / 是否強制 finalize）記 LLMCallTrace 或 stage_timings 方便 admin 觀測。

## 4. LLM exception envelope（spec: Agent loop SHALL convert LLM 4xx context-exceeded errors into the tool error envelope instead of propagating 5xx）

- [x] 4.0 實作 spec requirement「Agent loop SHALL convert LLM 4xx context-exceeded errors into the tool error envelope instead of propagating 5xx」。
- [x] 4.1 包 `chat.completions.create(...)` call 在 try/except 內：catch `openai.BadRequestError`（從 `from openai import BadRequestError`）；若 exception.message 或 .body 含 `"ContextWindowExceededError"` 或 `"context_length"`，分類 `kind="context_exceeded"`；否則先 re-raise（其他 400 case 由 endpoint handler 處理）。
- [x] 4.2 對 `kind="context_exceeded"`：build user_hint = `"這題涉及內容太多，我只能列出部分結果；試試把問題拆小，譬如指定單一集數。"`；設 `answer = user_hint`、`agent_truncated=True`、`break` out of 迴圈。
- [x] 4.3 把 catch 到的 exception class name + 第一句 internal_message 寫進 synthesised `LLMCallTrace`（`finish_reason="context_exceeded"`，其他欄位最佳估計）讓 admin debug_trace 看得到原因；user-facing answer 維持 user_hint 不含 internal 字眼。

## 5. Unit tests

- [x] 5.1 新建 `backend/tests/test_agent_token_budget.py`，4-5 個 case：
  - (a) `_truncate_for_llm` 對 20000-char string + cap=8000 回 8000+suffix；對 300-char + cap=8000 原樣回
  - (b) `_estimate_messages_tokens` 對 fixture messages 拿 reasonable 數字（tiktoken path）+ fall back path（mock ImportError）
  - (c) budget guard：mock messages 含 system + user + 3 tool message 共估 105000 tokens，呼 `_apply_budget_guard(budget=100000)` 後最舊 tool 被移除
  - (d) budget guard 第二輪仍超 → append truncate-system + 回 `agent_truncated=True`
  - (e) context-exceeded envelope：mock `chat.completions.create` raise `BadRequestError(body={"error":{"message":"ContextWindowExceededError ..."}})`，run_agent 回 `agent_truncated=True` + answer 含「內容太多」字眼 + 不含 `BadRequestError`
- [x] 5.2 跑 `pytest backend/tests/test_agent_token_budget.py -v` 全綠；跑既有 5 個 agent test file 確認無 regression。

## 6. Prod smoke + archive

- [x] 6.1 push commit；等 Zeabur build RUNNING。
- [x] 6.2 用 backdoor session 對 b20 那題 nohup 連跑 5 次 query (`curl POST /shows/.../query`)，全部 HTTP 200 + answer 文字不含「技術問題 / 系統錯誤 / 資料存取 / BadRequestError」。
- [x] 6.3 完整跑一輪 `run_chat_agent_eval.py` against `extended-multi-turn-40.json`；驗證 empty-answer turns = 0/40（baseline 是 1/40）；append 結果到 `docs/runbooks/eval-metrics-log.md`。
- [x] 6.4 `/spectra-archive agent-token-budget-and-tool-truncate`；release log 起草 entry（tag=fix，標題「對話模式不會再因為單題太複雜直接出錯」）；更新 `project_pending_changes.md` 反映已收尾。
