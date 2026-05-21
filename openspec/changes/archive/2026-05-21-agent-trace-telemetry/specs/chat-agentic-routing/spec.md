## ADDED Requirements

### Requirement: Agent loop emits per-stage telemetry trace

The agent loop (`backend/app/services/chat_agent/agent.py::run_agent`) SHALL collect timing and call-detail trace data during every chat turn and return it in `ChatAgentResult`. The trace SHALL contain three components: (1) `llm_calls: list[LLMCallTrace]` — one entry per LLM API call in the loop with `round_index`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `finish_reason`, and `had_tool_calls`; (2) `stage_timings: StageTimings` — elapsed milliseconds for `build_messages_ms`, `state_load_ms`, `state_save_ms`, `history_summary_ms`, and `llm_loop_total_ms`; (3) existing `tool_calls: list[ToolCallTrace]` with new optional field `result_full: str | None` containing the complete tool-result JSON when admin trace mode is active. Stage timing collection MUST use `time.perf_counter()` pairs and MUST NOT change the existing fail-open behavior of state-load/save or history-summary stages.

#### Scenario: Trace populated on successful chat turn

- **WHEN** `run_agent` completes a chat turn with at least one LLM call and at least one tool dispatch
- **THEN** `ChatAgentResult.llm_calls` SHALL contain one entry per LLM API call made during the loop
- **AND** each `LLMCallTrace` SHALL have non-negative `latency_ms` and a non-empty `finish_reason`
- **AND** `ChatAgentResult.stage_timings.llm_loop_total_ms` SHALL be greater than zero
- **AND** every entry in `ChatAgentResult.tool_calls` SHALL retain its existing `latency_ms` and `result_summary` fields

#### Scenario: Trace populated on agent-truncated turn

- **GIVEN** the agent reaches `settings.agentic_chat_max_iterations` without a terminal answer
- **WHEN** the loop exits via the truncate path
- **THEN** `ChatAgentResult.llm_calls` SHALL contain exactly `agentic_chat_max_iterations` entries
- **AND** `ChatAgentResult.agent_truncated` SHALL be `true`
- **AND** the trace data SHALL be complete (no missing entries)

#### Scenario: Stage timing for fail-open path

- **GIVEN** `state_store.save` raises an exception during the post-loop save
- **WHEN** the existing fail-open catch handles the exception
- **THEN** `ChatAgentResult.stage_timings.state_save_ms` SHALL contain a non-negative elapsed-ms value (representing how long the failed attempt took)
- **AND** the chat response SHALL NOT be a 5xx
- **AND** the `logger.exception` call for the save failure SHALL still execute


### Requirement: Query endpoint exposes trace under admin debug gate

The chat-mode query endpoint (`POST /shows/{show_id}/query` in `backend/app/api/query.py::query_show`) SHALL accept an optional query parameter `debug_trace: bool = false`. When `debug_trace=true` AND the requesting session belongs to an admin user (`current_user.is_admin == true`), the response body SHALL include a `trace` object containing `llm_calls`, `stage_timings`, and `tool_calls` with `result_full` populated. When either condition is unmet (no query param, or non-admin session), the response SHALL NOT include the `trace` field, and `result_full` in any returned tool-call data SHALL be `null`. The gate check SHALL NOT raise 4xx for non-admin requests with `debug_trace=true` — the parameter SHALL be silently ignored.

#### Scenario: Admin session with debug_trace returns full trace

- **GIVEN** an authenticated admin session and `ENABLE_AGENTIC_CHAT=true`
- **WHEN** the admin sends `POST /shows/{show_id}/query?debug_trace=true` with body `{"question": "...", "mode": "chat"}`
- **THEN** the response SHALL be HTTP 200
- **AND** the response body SHALL contain a `trace` field with `llm_calls`, `stage_timings`, and `tool_calls` arrays
- **AND** each entry in `trace.tool_calls` SHALL have a non-null `result_full` field

#### Scenario: Non-admin session with debug_trace is silently denied

- **GIVEN** an authenticated non-admin session
- **WHEN** the user sends `POST /shows/{show_id}/query?debug_trace=true`
- **THEN** the response SHALL be HTTP 200 (not 403)
- **AND** the response body SHALL NOT contain a `trace` field
- **AND** `result_full` SHALL NOT appear in any tool-call data

#### Scenario: Admin session without debug_trace gets normal response

- **GIVEN** an authenticated admin session
- **WHEN** the admin sends `POST /shows/{show_id}/query` without the `debug_trace` parameter
- **THEN** the response body SHALL NOT contain a `trace` field
- **AND** the response SHALL be identical in shape to the pre-change response


### Requirement: dogfood_trace_dump script captures 30-question trace for offline analysis

A local script `backend/scripts/dogfood_trace_dump.py` SHALL repeatedly call the prod `/query?debug_trace=true` endpoint for each question in `backend/eval/datasets/this-not-that-cool.json` (30 questions), using an admin session cookie loaded from env, and SHALL write the collected responses (including full trace data) to `.tmp/dogfood_trace_2026-05-22.json`. The script SHALL retry once on HTTP 5xx or timeout, and SHALL record `{"error": "<msg>"}` in place of trace for questions that fail both attempts so the dump remains complete. The script SHALL NOT commit any output to git (`.tmp/` is gitignored).

#### Scenario: All 30 questions succeed

- **GIVEN** prod is healthy, admin session cookie is valid, and feature flag is enabled
- **WHEN** the operator runs `python3 backend/scripts/dogfood_trace_dump.py`
- **THEN** the script SHALL write `.tmp/dogfood_trace_2026-05-22.json`
- **AND** the file SHALL contain exactly 30 entries
- **AND** each entry SHALL contain a `trace` field with `llm_calls`, `stage_timings`, and `tool_calls` arrays

#### Scenario: Single question times out, others succeed

- **GIVEN** one question's prod call times out twice
- **WHEN** the script processes that question
- **THEN** the entry for that question SHALL contain `{"id": "<qid>", "error": "<msg>"}` instead of `trace`
- **AND** the script SHALL continue with the remaining questions
- **AND** the final file SHALL still contain 30 entries (one with error, others with trace)
