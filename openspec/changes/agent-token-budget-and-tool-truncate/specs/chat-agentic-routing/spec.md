## ADDED Requirements

### Requirement: Tool dispatch SHALL truncate result strings sent to the LLM

`_dispatch_tool` SHALL truncate the JSON-encoded tool result that is appended as a `role="tool"` message to `messages` (and used as the LLM-facing `result_summary`) so its length does not exceed `settings.agentic_tool_result_max_chars` (default 8000 characters). When truncation occurs, the truncated string SHALL end with `... (truncated, <N> chars omitted)` where N is the number of characters removed. The `ToolCallTrace.result_full` field SHALL retain the full untruncated JSON (it is already scrubbed for non-admin responses by `_agent_result_to_response`), so admin `debug_trace=true` observability is not degraded.

#### Scenario: Long tool result is truncated for the LLM but kept for admin trace

- **GIVEN** a `get_episode_segments` call whose JSON-encoded result is 20000 characters
- **WHEN** `_dispatch_tool` returns and the agent appends a `role="tool"` message
- **THEN** the `content` of that tool message SHALL be at most 8000 + length-of-suffix characters
- **AND** the suffix SHALL include the literal text `(truncated,`
- **AND** the corresponding `ToolCallTrace.result_full` SHALL be exactly 20000 characters (untruncated)

#### Scenario: Short tool result is not modified

- **GIVEN** a `find_episodes_by_guest` call whose JSON-encoded result is 300 characters
- **WHEN** `_dispatch_tool` returns
- **THEN** the LLM-facing `content` SHALL be exactly 300 characters
- **AND** the suffix `(truncated,` SHALL NOT appear

### Requirement: Agent loop SHALL guard per-round token budget before each LLM call

Before every `client.chat.completions.create` call in `run_agent`, the agent loop SHALL estimate the total tokens in the current `messages` list (using a `tiktoken` encoder for the gpt-4o family; fall back to `len(text) / 4` if the encoder is unavailable). When the estimate exceeds `settings.agentic_chat_messages_max_tokens` (default 100000), the loop SHALL:

1. Remove the oldest `role="tool"` message from `messages` (preserving the leading system message and the most recent user / assistant pair).
2. Re-estimate. Repeat step 1 until the estimate is at or below budget OR no removable tool message remains.
3. If still over budget after step 2, append a `role="system"` message with content `"Context truncated by budget guard. Wrap up with the information you already have."` and break out of the iteration loop. The most recent assistant message (or an empty string if none) SHALL be returned as the final answer, and `ChatAgentResult.agent_truncated` SHALL be set to `true`.

#### Scenario: Budget guard removes oldest tool message and continues

- **GIVEN** `messages` has system + user + 3 tool messages (oldest first) + 1 assistant draft, totalling 105000 estimated tokens (budget 100000)
- **WHEN** the agent enters the next LLM round and runs the guard
- **THEN** the oldest tool message SHALL be removed
- **AND** if the new estimate is now ≤ 100000, the LLM call SHALL proceed as normal

#### Scenario: Budget guard cannot fit and finalises

- **GIVEN** `messages` still exceeds 100000 tokens after every removable tool message has been popped
- **WHEN** the guard runs
- **THEN** a `role="system"` "Context truncated by budget guard" message SHALL be appended
- **AND** the agent loop SHALL break
- **AND** `ChatAgentResult.agent_truncated` SHALL be `true`

### Requirement: Agent loop SHALL convert LLM 4xx context-exceeded errors into the tool error envelope instead of propagating 5xx

When the LLM `chat.completions.create` call raises `openai.BadRequestError` (or any HTTP 400 surfaced as `litellm.ContextWindowExceededError` via the AI Hub proxy), the agent loop SHALL catch the exception, classify it with `kind="context_exceeded"` (an extension of the `_classify_exception` switch from `chat-tool-error-isolation`), produce a user-facing answer derived from the envelope's `user_hint` ("這題涉及內容太多，我只能列出部分結果；試試把問題拆小，譬如指定單一集數"), set `ChatAgentResult.agent_truncated = true`, and return without raising an HTTP 5xx. The exception class name and `internal_message` SHALL be recorded in the corresponding `LLMCallTrace` (or a synthesised trace entry) so admin `debug_trace=true` can inspect the cause, but SHALL NOT appear in the user-facing answer text.

#### Scenario: ContextWindowExceededError is converted to user-friendly answer

- **GIVEN** the LLM `chat.completions.create` raises `BadRequestError` whose body contains `"ContextWindowExceededError"` and `model=gpt-4o`
- **WHEN** the agent loop processes that round
- **THEN** the HTTP response status SHALL be 200 (not 5xx)
- **AND** `ChatResponse.answer` SHALL contain the `user_hint` text (substring match: "這題涉及內容太多" or equivalent)
- **AND** `ChatResponse.answer` SHALL NOT contain the substring `"BadRequestError"`, `"ContextWindowExceededError"`, or `"technical issue"`
- **AND** `ChatResponse.agent_truncated` SHALL be `true`

#### Scenario: Unrelated LLM 5xx still propagates

- **GIVEN** the LLM call raises `openai.APIConnectionError` (network failure, not a 4xx)
- **WHEN** the agent loop runs
- **THEN** the existing behavior SHALL apply (no envelope conversion for connection errors; existing endpoint-level error handlers take over)
