# chat-agentic-routing Specification

## Purpose

TBD - created by archiving change 'chat-agentic-tool-routing'. Update Purpose after archive.

## Requirements

### Requirement: Agent loop drives chat-mode queries when feature flag is enabled

The backend SHALL provide an agent loop (`backend/app/services/chat_agent/agent.py::run_agent`) that, when `settings.enable_agentic_chat` is `true`, replaces the rule-based chat pipeline for `payload.mode != "search"` requests in `query_show`. The agent SHALL drive an OpenAI-compatible tool-calling loop against the AI Hub endpoint, with `max_iterations` upper-bounded by `settings.agentic_chat_max_iterations` (default 10). When the iteration limit is reached without a final answer message, the agent SHALL return the most recent LLM message as the answer and mark `agent_truncated=true` in the result. The agent SHALL NOT propagate tool-dispatch exceptions as HTTP 5xx; every tool exception SHALL be caught and converted into a JSON `{"error": "<ExceptionClass>: <msg>"}` payload that is appended as a tool-result message so the LLM can decide how to respond.

#### Scenario: Happy-path enumeration query

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the user asks "歌單有哪幾集？"
- **WHEN** `query_show` dispatches to `run_agent`
- **THEN** the agent SHALL call `find_episodes_by_topic` at least once
- **AND** the returned `ChatAgentResult.answer` SHALL be a non-empty string
- **AND** `ChatAgentResult.tool_calls` SHALL contain at least one entry with `name="find_episodes_by_topic"`
- **AND** `agent_truncated` SHALL be `false`

#### Scenario: Tool raises exception is caught and converted

- **WHEN** a registered tool raises any `Exception` during dispatch
- **THEN** the agent loop SHALL catch the exception and append a tool-result message with body `{"error": "<ExceptionClass>: <message>"}`
- **AND** the agent SHALL continue the loop (not abort) until the LLM produces a final answer or the iteration cap is reached
- **AND** the HTTP response SHALL NOT be a 5xx solely because of the tool exception

#### Scenario: Iteration cap reached

- **GIVEN** the LLM keeps emitting tool calls and never produces a terminal answer message
- **WHEN** the loop reaches `settings.agentic_chat_max_iterations` iterations
- **THEN** the agent SHALL exit the loop
- **AND** `ChatAgentResult.agent_truncated` SHALL be `true`
- **AND** `ChatAgentResult.answer` SHALL be the most recent LLM message content (which MAY be empty)


<!-- @trace
source: chat-agentic-tool-routing
updated: 2026-05-21
code:
  - .agents/skills/spectra-analyze/SKILL.md
  - .agents/skills/spectra-commit/SKILL.md
  - .agents/skills/spectra-ingest/SKILL.md
  - backend/scripts/run_chat_agent_eval.py
  - backend/app/services/chat_agent/__init__.py
  - backend/app/core/config.py
  - .agents/skills/spectra-verify/SKILL.md
  - backend/scripts/agentic_bakeoff/results/comparison.md
  - backend/app/services/chat_agent/prompts.py
  - .codex/config.toml
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/services/chat_agent/agent.py
  - .agents/skills/spectra-archive/SKILL.md
  - backend/scripts/agentic_bakeoff/results/a_native_openai_20260519T100220Z.json
  - .agents/skills/spectra-propose/SKILL.md
  - .agents/skills/spectra-audit/SKILL.md
  - backend/app/services/episode_finders.py
  - .agents/skills/spectra-discuss/SKILL.md
  - .tmp/citation-unify-q1.png
  - .tmp/citation-unify-q3.png
  - AGENTS.md
  - backend/app/services/chat_agent/state.py
  - .agents/skills/spectra-apply/SKILL.md
  - backend/app/services/chat_agent/memory.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - backend/app/schemas/query.py
  - .agents/skills/rag-eval-runner/SKILL.md
  - .agents/skills/spectra-drift/SKILL.md
  - .codex/hooks.json
  - .agents/skills/spectra-ask/SKILL.md
  - .agents/skills/spectra-debug/SKILL.md
  - .tmp/citation-unify-q2.png
  - .tmp/citation-unify-zh-all.png
  - backend/app/services/chat_agent/tools.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/app/api/query.py
tests:
  - backend/tests/test_chat_session_state.py
  - backend/tests/test_quota_decrement_uniform.py
  - backend/tests/test_chat_agent_multi_turn.py
  - backend/tests/test_chat_agent_loop.py
  - backend/tests/test_chat_agent_memory.py
-->

---
### Requirement: Tool registry exposes eleven callables backed by real services

The backend SHALL register exactly eleven callables in `chat_agent.tools.TOOLS`, corresponding to nine numbered tools from `agentic-framework-bakeoff`'s 9-tool spec (with tool 7 split into `search_within_episode` / `search_across_episodes` / `search_in_episodes` and tool 9 split into `pin_episode` / `unpin_episode`). Each callable SHALL declare a Pydantic `BaseModel` as its input schema. The OpenAI tool function schema SHALL be derived from that Pydantic model automatically (no hand-written JSON Schema). All previously stubbed tools from the bake-off SHALL be wired to production services:

- `get_episode_summary` SHALL read from the episode summary store via `summary_pipeline`.
- `get_episode_segments` SHALL read from `topic_segmentation`.
- `search_within_episode` and `search_in_episodes` SHALL call `rag.retrieve_hybrid` with `episode_id_filter` set.
- `search_across_episodes` SHALL call `rag.retrieve_hybrid` without an episode filter.
- `find_episode_by_ref` SHALL call `episode_finders.find_by_ref`.
- `find_episodes_by_guest` / `find_episodes_by_topic` / `find_episodes_by_date` SHALL call the corresponding `episode_finders` functions.
- `get_show_overview` SHALL read from the show table.
- `pin_episode` and `unpin_episode` SHALL write to `ChatSessionState.focused_episode_id`.

#### Scenario: Input schema validation failure returns error JSON to LLM

- **GIVEN** the LLM emits a tool call with an argument that fails the Pydantic `BaseModel` validation (e.g., `episode_id="not-a-uuid"`)
- **WHEN** `_dispatch_tool` validates the arguments
- **THEN** the tool function body SHALL NOT be executed
- **AND** the tool-result message SHALL contain `{"error": "ValidationError: ..."}` with the validation detail
- **AND** the agent SHALL continue the loop so the LLM can apologise to the user

#### Scenario: Enumeration tool writes back to L1 state

- **GIVEN** the LLM calls `find_episodes_by_topic(topic="歌單")` and the function returns episode UUIDs
- **WHEN** the tool dispatcher records the result
- **THEN** the dispatcher SHALL also update the current `ChatSessionState.last_enumeration_episodes` with the returned episode UUIDs (most recent up to 20, FIFO truncated)
- **AND** the dispatcher SHALL update `ChatSessionState.last_enumeration_at` to the current timestamp
- **AND** the state SHALL be persisted to Redis with TTL refreshed


<!-- @trace
source: chat-agentic-tool-routing
updated: 2026-05-21
code:
  - .agents/skills/spectra-analyze/SKILL.md
  - .agents/skills/spectra-commit/SKILL.md
  - .agents/skills/spectra-ingest/SKILL.md
  - backend/scripts/run_chat_agent_eval.py
  - backend/app/services/chat_agent/__init__.py
  - backend/app/core/config.py
  - .agents/skills/spectra-verify/SKILL.md
  - backend/scripts/agentic_bakeoff/results/comparison.md
  - backend/app/services/chat_agent/prompts.py
  - .codex/config.toml
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/services/chat_agent/agent.py
  - .agents/skills/spectra-archive/SKILL.md
  - backend/scripts/agentic_bakeoff/results/a_native_openai_20260519T100220Z.json
  - .agents/skills/spectra-propose/SKILL.md
  - .agents/skills/spectra-audit/SKILL.md
  - backend/app/services/episode_finders.py
  - .agents/skills/spectra-discuss/SKILL.md
  - .tmp/citation-unify-q1.png
  - .tmp/citation-unify-q3.png
  - AGENTS.md
  - backend/app/services/chat_agent/state.py
  - .agents/skills/spectra-apply/SKILL.md
  - backend/app/services/chat_agent/memory.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - backend/app/schemas/query.py
  - .agents/skills/rag-eval-runner/SKILL.md
  - .agents/skills/spectra-drift/SKILL.md
  - .codex/hooks.json
  - .agents/skills/spectra-ask/SKILL.md
  - .agents/skills/spectra-debug/SKILL.md
  - .tmp/citation-unify-q2.png
  - .tmp/citation-unify-zh-all.png
  - backend/app/services/chat_agent/tools.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/app/api/query.py
tests:
  - backend/tests/test_chat_session_state.py
  - backend/tests/test_quota_decrement_uniform.py
  - backend/tests/test_chat_agent_multi_turn.py
  - backend/tests/test_chat_agent_loop.py
  - backend/tests/test_chat_agent_memory.py
-->

---
### Requirement: System prompt instructs tool-eager grounded behaviour

The agent's system prompt (`chat_agent.prompts.SYSTEM_PROMPT`) SHALL contain three sections, in this order: (1) a role description identifying the agent as PodcastRAG's chat agent; (2) a tool-eager instruction stating that the agent MUST call at least one tool before refusing or answering whenever the user asks about specific information (episode numbers, hosts, guests, content); (3) a grounded-refusal instruction stating that when all relevant tools return empty, the agent MUST explicitly say it cannot find X rather than fabricate, and when input schema is invalid, the agent MUST ask the user to clarify rather than guess.

#### Scenario: Specific-information query triggers tool call

- **GIVEN** the user asks "馬世芳上過哪一集？" (a specific information query about a guest)
- **WHEN** the agent processes the request
- **THEN** the agent SHALL call at least one tool (e.g., `find_episodes_by_guest`) before producing the final answer
- **AND** the answer SHALL NOT be a flat refusal without any tool invocation


<!-- @trace
source: chat-agentic-tool-routing
updated: 2026-05-21
code:
  - .agents/skills/spectra-analyze/SKILL.md
  - .agents/skills/spectra-commit/SKILL.md
  - .agents/skills/spectra-ingest/SKILL.md
  - backend/scripts/run_chat_agent_eval.py
  - backend/app/services/chat_agent/__init__.py
  - backend/app/core/config.py
  - .agents/skills/spectra-verify/SKILL.md
  - backend/scripts/agentic_bakeoff/results/comparison.md
  - backend/app/services/chat_agent/prompts.py
  - .codex/config.toml
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/services/chat_agent/agent.py
  - .agents/skills/spectra-archive/SKILL.md
  - backend/scripts/agentic_bakeoff/results/a_native_openai_20260519T100220Z.json
  - .agents/skills/spectra-propose/SKILL.md
  - .agents/skills/spectra-audit/SKILL.md
  - backend/app/services/episode_finders.py
  - .agents/skills/spectra-discuss/SKILL.md
  - .tmp/citation-unify-q1.png
  - .tmp/citation-unify-q3.png
  - AGENTS.md
  - backend/app/services/chat_agent/state.py
  - .agents/skills/spectra-apply/SKILL.md
  - backend/app/services/chat_agent/memory.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - backend/app/schemas/query.py
  - .agents/skills/rag-eval-runner/SKILL.md
  - .agents/skills/spectra-drift/SKILL.md
  - .codex/hooks.json
  - .agents/skills/spectra-ask/SKILL.md
  - .agents/skills/spectra-debug/SKILL.md
  - .tmp/citation-unify-q2.png
  - .tmp/citation-unify-zh-all.png
  - backend/app/services/chat_agent/tools.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/app/api/query.py
tests:
  - backend/tests/test_chat_session_state.py
  - backend/tests/test_quota_decrement_uniform.py
  - backend/tests/test_chat_agent_multi_turn.py
  - backend/tests/test_chat_agent_loop.py
  - backend/tests/test_chat_agent_memory.py
-->

---
### Requirement: Agent response schema exposes optional tool-call trace

The `ChatResponse` Pydantic schema SHALL include two optional fields populated only when the request was served by the agent loop (i.e., `ENABLE_AGENTIC_CHAT=true`):

- `tool_calls: list[ToolCallTrace] | None` — each entry SHALL contain `name: str`, `args: dict`, `result_summary: str` (truncated to ≤ 500 chars), `raised: str | None` (exception class name or null), `latency_ms: float`.
- `agent_truncated: bool` — `true` when the iteration cap was hit before a terminal answer.

When `ENABLE_AGENTIC_CHAT=false`, both fields SHALL be `null` / `false` so that the rule-based response shape is preserved.

#### Scenario: Flag-disabled response omits agent fields

- **GIVEN** `ENABLE_AGENTIC_CHAT=false`
- **WHEN** `query_show` returns a chat response
- **THEN** `tool_calls` SHALL be `null`
- **AND** `agent_truncated` SHALL be `false`

#### Scenario: Flag-enabled response populates agent fields

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and a tool was called during the agent loop
- **WHEN** `query_show` returns a chat response
- **THEN** `tool_calls` SHALL be a list with at least one entry
- **AND** each entry's `result_summary` SHALL be ≤ 500 characters


<!-- @trace
source: chat-agentic-tool-routing
updated: 2026-05-21
code:
  - .agents/skills/spectra-analyze/SKILL.md
  - .agents/skills/spectra-commit/SKILL.md
  - .agents/skills/spectra-ingest/SKILL.md
  - backend/scripts/run_chat_agent_eval.py
  - backend/app/services/chat_agent/__init__.py
  - backend/app/core/config.py
  - .agents/skills/spectra-verify/SKILL.md
  - backend/scripts/agentic_bakeoff/results/comparison.md
  - backend/app/services/chat_agent/prompts.py
  - .codex/config.toml
  - .tmp/citation-unify-en-collapsed.png
  - backend/app/services/chat_agent/agent.py
  - .agents/skills/spectra-archive/SKILL.md
  - backend/scripts/agentic_bakeoff/results/a_native_openai_20260519T100220Z.json
  - .agents/skills/spectra-propose/SKILL.md
  - .agents/skills/spectra-audit/SKILL.md
  - backend/app/services/episode_finders.py
  - .agents/skills/spectra-discuss/SKILL.md
  - .tmp/citation-unify-q1.png
  - .tmp/citation-unify-q3.png
  - AGENTS.md
  - backend/app/services/chat_agent/state.py
  - .agents/skills/spectra-apply/SKILL.md
  - backend/app/services/chat_agent/memory.py
  - .tmp/citation-unify-q1-q2-q3-zh-expanded.png
  - backend/app/schemas/query.py
  - .agents/skills/rag-eval-runner/SKILL.md
  - .agents/skills/spectra-drift/SKILL.md
  - .codex/hooks.json
  - .agents/skills/spectra-ask/SKILL.md
  - .agents/skills/spectra-debug/SKILL.md
  - .tmp/citation-unify-q2.png
  - .tmp/citation-unify-zh-all.png
  - backend/app/services/chat_agent/tools.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/app/api/query.py
tests:
  - backend/tests/test_chat_session_state.py
  - backend/tests/test_quota_decrement_uniform.py
  - backend/tests/test_chat_agent_multi_turn.py
  - backend/tests/test_chat_agent_loop.py
  - backend/tests/test_chat_agent_memory.py
-->

---
### Requirement: Eval gate blocks rollout of agentic chat default

Before flipping the `enable_agentic_chat` Python default from `False` to `True`, an evaluation run against `backend/eval/datasets/extended-multi-turn-40.json` SHALL be performed against the Arm D (agentic) pipeline using the LLM-as-judge (`backend/scripts/run_llm_judge_multi_turn.py`) calibrated by `_judge_minisset.json`. The agentic pipeline SHALL meet all of the following gates:

- `answer_match_mean` (keyword baseline) MUST NOT drop by more than 5 percentage points vs the stored baseline `backend/eval/results/chat_eval_agentic_2026-05-22.json`.
- LLM judge `answer_quality_mean` MUST be ≥ 0.55 (absolute threshold; no same-dataset baseline available).
- The ratio of turns labelled `hallucination_severity == "severe"` MUST be ≤ 20% of total turns scored.
- Of the four multi-turn dialogs containing ordinal-reference follow-ups, at least 1 SHALL produce an answer that maps to the corresponding `episode_id` from the prior enumeration.

Evaluation results SHALL be persisted under `backend/eval/results/` with a date-stamped filename, and the gate decision SHALL be recorded in the change's design.md before merging the default flip. Stricter thresholds (severe count == 0, ordinal hits ≥ 3/4) were considered and explicitly waived in design.md "2026-05-22 校準紀錄" because the blocking failure modes (LLM grounding weakness, prompt-instruction non-compliance) are not introduced by this change and require an independent follow-up `agentic-prompt-grounding-and-ordinal-tool`.

#### Scenario: answer_match regression blocks default flip

- **GIVEN** the eval run shows agentic `answer_match_mean` more than 5pp below the stored baseline
- **WHEN** anyone proposes flipping the `enable_agentic_chat` Python default
- **THEN** the change SHALL be blocked until the regression is addressed or the gate is explicitly waived with sign-off recorded in design.md

#### Scenario: answer_quality below absolute threshold blocks default flip

- **GIVEN** the eval run shows agentic `answer_quality_mean` below 0.55
- **WHEN** anyone proposes flipping the `enable_agentic_chat` Python default
- **THEN** the change SHALL be blocked until the regression is addressed

#### Scenario: Severe hallucination rate above 20% blocks default flip

- **GIVEN** the eval run shows more than 20% of scored turns with `hallucination_severity == "severe"`
- **WHEN** anyone proposes flipping the `enable_agentic_chat` Python default
- **THEN** the change SHALL be blocked until the offending turns' root cause is addressed

#### Scenario: Zero ordinal-reference hits blocks default flip

- **GIVEN** the eval run shows zero of the four ordinal-reference follow-ups produce the correct prior-enumeration `episode_id`
- **WHEN** anyone proposes flipping the `enable_agentic_chat` Python default
- **THEN** the change SHALL be blocked until at least one ordinal carry path works

---
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


<!-- @trace
source: agent-trace-telemetry
updated: 2026-05-21
code:
  - backend/app/services/chat_agent/agent.py
  - backend/app/schemas/query.py
  - backend/scripts/dogfood_trace_dump.py
  - backend/eval/datasets/README.md
  - backend/app/api/query.py
  - docs/case-studies/sync-naming-redesign.md
  - backend/eval/datasets/extended-multi-turn-40.json
tests:
  - backend/tests/test_chat_agent_telemetry.py
  - backend/tests/test_query_debug_trace_gate.py
-->

---
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


<!-- @trace
source: agent-trace-telemetry
updated: 2026-05-21
code:
  - backend/app/services/chat_agent/agent.py
  - backend/app/schemas/query.py
  - backend/scripts/dogfood_trace_dump.py
  - backend/eval/datasets/README.md
  - backend/app/api/query.py
  - docs/case-studies/sync-naming-redesign.md
  - backend/eval/datasets/extended-multi-turn-40.json
tests:
  - backend/tests/test_chat_agent_telemetry.py
  - backend/tests/test_query_debug_trace_gate.py
-->

---
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

<!-- @trace
source: agent-trace-telemetry
updated: 2026-05-21
code:
  - backend/app/services/chat_agent/agent.py
  - backend/app/schemas/query.py
  - backend/scripts/dogfood_trace_dump.py
  - backend/eval/datasets/README.md
  - backend/app/api/query.py
  - docs/case-studies/sync-naming-redesign.md
  - backend/eval/datasets/extended-multi-turn-40.json
tests:
  - backend/tests/test_chat_agent_telemetry.py
  - backend/tests/test_query_debug_trace_gate.py
-->

---
### Requirement: Agent tool dispatcher SHALL isolate tool errors via SAVEPOINT and return structured error envelope

The agent tool dispatcher (`backend/app/services/chat_agent/tools.py::_dispatch_tool`) SHALL wrap every tool callable invocation in a SQLAlchemy nested transaction (`begin_nested()` → PostgreSQL SAVEPOINT). When the tool callable raises any exception, the SAVEPOINT SHALL be rolled back automatically so the outer `AsyncSession` retains a clean transaction; subsequent tool calls in the same agent loop SHALL be able to execute database queries without encountering `InFailedSQLTransactionError`.

When a tool callable raises, the dispatcher SHALL convert the exception into a structured **Tool error envelope** with shape `{"ok": false, "kind": "validation" | "schema" | "transient" | "not_found" | "unknown", "internal_message": "<ExceptionClass>: <msg>", "user_hint": "<friendly zh-TW text>"}`. A helper `_classify_exception(exc)` SHALL classify the exception into one of those five `kind` values using a dispatch table:

- `pydantic.ValidationError` → `validation`
- `sqlalchemy.exc.ProgrammingError`, `IntegrityError`, `DataError` → `schema`
- `asyncio.TimeoutError`, `asyncpg.PostgresConnectionError`, `OperationalError` → `transient`
- `LookupError` (or future project `NotFoundError`) → `not_found`
- anything else → `unknown`

The dispatcher SHALL NOT return the legacy `{"error": "..."}` shape on failure — every failure path returns the envelope. Existing successful tool results SHALL remain unchanged (no `ok: true` wrapping required).

#### Scenario: Tool raises ProgrammingError, next tool still works

- **GIVEN** an agent loop where the first tool callable raises `ProgrammingError`
- **WHEN** `_dispatch_tool` returns the envelope and the agent loop proceeds to a second tool callable that issues a SELECT on the same `AsyncSession`
- **THEN** the second tool's query SHALL execute successfully (no `InFailedSQLTransactionError`)
- **AND** the first tool's `ToolCallTrace.raised` SHALL be the exception class name (e.g. `"ProgrammingError"`)
- **AND** the first tool's result dict SHALL contain keys `ok`, `kind`, `internal_message`, `user_hint`

#### Scenario: Schema error classified and user_hint sanitised

- **GIVEN** a tool callable raises `sqlalchemy.exc.ProgrammingError("column ts.start_seconds does not exist")`
- **WHEN** `_dispatch_tool` catches the exception
- **THEN** the returned envelope SHALL have `kind == "schema"`
- **AND** the envelope's `internal_message` SHALL contain `"ProgrammingError"` and the column reference
- **AND** the envelope's `user_hint` SHALL NOT contain `"ProgrammingError"`, the column name, or the word "transaction"

#### Scenario: Validation error classified

- **GIVEN** a tool is invoked with arguments that fail Pydantic schema validation
- **WHEN** `_dispatch_tool` runs `spec.input_model.model_validate(args)` and catches `ValidationError`
- **THEN** the returned envelope SHALL have `kind == "validation"`
- **AND** the envelope's `internal_message` SHALL begin with `"ValidationError:"`
- **AND** the `user_hint` SHALL be a generic zh-TW phrasing such as "查詢條件有點不太對" (validation-flavoured)

#### Scenario: Unknown exception falls back gracefully

- **GIVEN** a tool callable raises an exception type not in the classifier dispatch table (e.g. `RuntimeError`)
- **WHEN** `_dispatch_tool` catches the exception
- **THEN** the returned envelope SHALL have `kind == "unknown"`
- **AND** the envelope's `user_hint` SHALL be a generic zh-TW phrasing such as "這次查詢遇到一點狀況"


<!-- @trace
source: chat-tool-error-isolation
updated: 2026-05-22
code:
  - backend/app/services/chat_agent/tools.py
  - backend/app/services/chat_agent/prompts.py
tests:
  - backend/tests/test_chat_tool_error_isolation.py
  - backend/tests/test_chat_agent_multi_turn.py
  - backend/tests/test_chat_agent_loop.py
  - backend/tests/test_chat_agent_telemetry.py
-->

---
### Requirement: Agent system prompt SHALL instruct the LLM to use `user_hint` and never expose internal error details

The agent system prompt (assembled by `backend/app/services/chat_agent/memory.py::build_messages`) SHALL include an explicit rule and example that direct the LLM, when a tool result contains `"ok": false`, to base its user-facing response on the envelope's `user_hint` field; the LLM SHALL NOT output `internal_message`, exception class names (e.g. `ProgrammingError`, `IntegrityError`), or phrases that imply internal system failure (e.g. "技術問題", "系統查詢時遇到", "資料存取似乎遇到問題").

#### Scenario: Tool result with `ok: false` produces user-friendly answer

- **GIVEN** the agent system prompt is loaded and a tool returns `{"ok": false, "kind": "schema", "internal_message": "ProgrammingError: column ts.start_seconds does not exist", "user_hint": "這次查詢沒撈到完整資料"}`
- **WHEN** the LLM produces the final answer in the next round
- **THEN** the answer text SHALL be a paraphrase / extension of `user_hint`
- **AND** the answer SHALL NOT contain `"ProgrammingError"`, `"column ts.start_seconds"`, `"技術問題"`, `"系統查詢"`, or `"資料存取"`


<!-- @trace
source: chat-tool-error-isolation
updated: 2026-05-22
code:
  - backend/app/services/chat_agent/tools.py
  - backend/app/services/chat_agent/prompts.py
tests:
  - backend/tests/test_chat_tool_error_isolation.py
  - backend/tests/test_chat_agent_multi_turn.py
  - backend/tests/test_chat_agent_loop.py
  - backend/tests/test_chat_agent_telemetry.py
-->

---
### Requirement: `_get_episode_segments` SQL SHALL reference the real `transcript_segments` columns

The SQL query in `backend/app/services/chat_agent/tools.py::_EPISODE_SEGMENTS_SQL` SHALL select `ts.start_time` and `ts.end_time` (aliased to `start_sec` and `end_sec` for the LLM response payload) and SHALL `ORDER BY ts.start_time ASC`. The previous column references `ts.start_seconds` / `ts.end_seconds` do not exist on the `transcript_segments` table per the `TranscriptSegment` model and SHALL NOT appear in the SQL.

#### Scenario: `_get_episode_segments` succeeds on prod schema

- **GIVEN** an episode with at least one transcript segment row in `transcript_segments`
- **WHEN** the agent invokes `get_episode_segments(episode_id, topic_filter=None)`
- **THEN** the tool result SHALL be a dict with key `segments` containing a non-empty list
- **AND** each segment SHALL have `start_sec` and `end_sec` as numeric values from the row's `start_time` / `end_time` columns
- **AND** the underlying SQL execution SHALL NOT raise `ProgrammingError`

<!-- @trace
source: chat-tool-error-isolation
updated: 2026-05-22
code:
  - backend/app/services/chat_agent/tools.py
  - backend/app/services/chat_agent/prompts.py
tests:
  - backend/tests/test_chat_tool_error_isolation.py
  - backend/tests/test_chat_agent_multi_turn.py
  - backend/tests/test_chat_agent_loop.py
  - backend/tests/test_chat_agent_telemetry.py
-->

---
### Requirement: Agentic path populates chunk-level citations from search-tool results

When `ENABLE_AGENTIC_CHAT=true` serves a chat-mode query, the `_agent_result_to_response` mapper in `backend/app/api/query.py` SHALL populate `ChatResponse.citations` by aggregating chunks from the `result_full["chunks"]` payload of every `ToolCallTrace` whose `name` is one of `search_within_episode`, `search_across_episodes`, or `search_in_episodes` and whose `raised` is null. The aggregation SHALL deduplicate by `chunk_id`, sort by `rrf_score` descending, and emit the top 5 entries as `ChunkHit` instances. When the agent invoked no successful search tool, `citations` SHALL be an empty list, matching the pre-flip behavior.

When a tool's `result_full` does not match the expected `{"chunks": [...]}` shape (missing key, wrong type, malformed entries), the mapper SHALL skip that tool call, log a warning, and continue processing remaining tool calls. The mapper SHALL NOT raise an exception that would surface as an HTTP 5xx to the caller.

#### Scenario: Agent invokes search_within_episode and citations are populated

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls `search_within_episode` once, returning 8 chunks
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.citations` SHALL contain 5 `ChunkHit` entries
- **AND** the entries SHALL be sorted by `rrf_score` descending
- **AND** each entry's `chunk_id` SHALL be unique

#### Scenario: Agent invokes multiple search tools and citations are deduplicated

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls both `search_across_episodes` and `search_within_episode`, with two overlapping `chunk_id` values
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.citations` SHALL NOT contain duplicate `chunk_id` values
- **AND** the entry list length SHALL be at most 5

#### Scenario: Agent invokes only listing tools and citations stay empty

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent only calls `find_episodes_by_guest`
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.citations` SHALL be `[]`

#### Scenario: Malformed tool result is skipped without 5xx

- **GIVEN** a `search_within_episode` tool call whose `result_full` is missing the `chunks` key
- **WHEN** `_agent_result_to_response` processes the result
- **THEN** that tool call SHALL be skipped
- **AND** the mapper SHALL log a warning
- **AND** the function SHALL return a valid `ChatResponse` (not raise an exception)

---
### Requirement: Agentic path populates enumeration_episodes from listing-tool and single-episode-lookup results

When `ENABLE_AGENTIC_CHAT=true` serves a chat-mode query, the `_agent_result_to_response` mapper SHALL populate `ChatResponse.enumeration_episodes` by aggregating episode entries from the `result_full` payload of every `ToolCallTrace` whose `raised` is null and whose `name` is in either of two groups:

- **Listing tools** (`find_episodes_by_guest`, `find_episodes_by_topic`, `find_episodes_by_date`): payload shape `{"episodes": [...]}` — every entry is appended.
- **Single-episode lookup tools** (`find_episode_by_ref`, `get_episode_summary`): payload shape `{"episode": {...}}` or `{"episode_id": ..., "title": ..., "summary": ...}` — exactly one entry is appended.

The aggregation SHALL deduplicate by `episode_id`, preserve the order in which the agent observed them, and emit each entry as an `EpisodeRef` instance.

When the agent invoked no successful listing or single-episode-lookup tool, `enumeration_episodes` SHALL remain `None` (the schema default), so that the frontend `EnumerationSection` collapses, matching the rule-based pipeline's behavior on non-enumeration queries.

#### Scenario: Agent invokes find_episodes_by_guest and enumeration is populated

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls `find_episodes_by_guest(name="楊大正")`, returning 2 episodes
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.enumeration_episodes` SHALL contain 2 `EpisodeRef` entries
- **AND** the entries SHALL preserve agent-observed order

#### Scenario: Agent invokes multiple listing tools and entries are deduplicated

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls both `find_episodes_by_topic` and `find_episodes_by_date`, with one overlapping `episode_id`
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.enumeration_episodes` SHALL NOT contain duplicate `episode_id` values

#### Scenario: Agent invokes only search tools and enumeration stays null

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent only calls `search_within_episode`
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.enumeration_episodes` SHALL be `null`

#### Scenario: Agent invokes find_episode_by_ref and enumeration contains one entry

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls `find_episode_by_ref(ref="EP143")` returning one episode
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.enumeration_episodes` SHALL contain exactly 1 `EpisodeRef` entry
- **AND** the entry SHALL carry the resolved `episode_id` and `title`

#### Scenario: Agent invokes get_episode_summary and enumeration contains one entry

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls `get_episode_summary(episode_id=X)` returning `{episode_id, title, summary}`
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.enumeration_episodes` SHALL contain exactly 1 `EpisodeRef` entry
- **AND** the entry's `ai_summary` SHALL equal the tool's `summary`

---
### Requirement: ENABLE_AGENTIC_CHAT Python default SHALL be true

The `enable_agentic_chat` field on `Settings` in `backend/app/core/config.py` SHALL default to `True`. The `if settings.enable_agentic_chat` branch in `query_show` and the rule-based pipeline below it SHALL remain in place for at least 30 days after the default flip, serving as a `ENABLE_AGENTIC_CHAT=false` kill-switch. A subsequent cleanup change SHALL be responsible for removing the flag, the branch, and the rule-based pipeline code once the observation window completes.

#### Scenario: Local backend without env override runs agentic loop

- **GIVEN** a developer runs the backend locally with no `ENABLE_AGENTIC_CHAT` env variable set
- **WHEN** a chat-mode query is dispatched
- **THEN** `query_show` SHALL invoke `run_agent` (not the rule-based pipeline)

#### Scenario: Explicit env false still bypasses agent

- **GIVEN** `ENABLE_AGENTIC_CHAT=false` is set in env
- **WHEN** a chat-mode query is dispatched
- **THEN** `query_show` SHALL invoke the rule-based pipeline (not `run_agent`)
