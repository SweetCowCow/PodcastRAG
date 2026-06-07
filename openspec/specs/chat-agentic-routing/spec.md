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

The backend SHALL register exactly fourteen callables in `chat_agent.tools.TOOLS`. This count comprises the original eleven from `agentic-framework-bakeoff`'s 9-tool spec (with tool 7 split into `search_within_episode` / `search_across_episodes` / `search_in_episodes` and tool 9 split into `pin_episode` / `unpin_episode`), plus `list_episodes` and `find_episodes_by_date` (added by prior changes without spec sync — recorded here for spec ↔ code alignment), plus `search_with_topic_prefilter` added by change `retrieval-cross-episode-episode-prefilter`. Each callable SHALL declare a Pydantic `BaseModel` as its input schema. The OpenAI tool function schema SHALL be derived from that Pydantic model automatically (no hand-written JSON Schema). All previously stubbed tools from the bake-off SHALL be wired to production services:

- `get_episode_summary` SHALL read from the episode summary store via `summary_pipeline`.
- `get_episode_segments` SHALL read from `topic_segmentation`.
- `search_within_episode` and `search_in_episodes` SHALL call `rag.retrieve_hybrid` with `episode_id_filter` set.
- `search_across_episodes` SHALL call `rag.retrieve_hybrid` without an episode filter. Its tool description SHALL note that it is the fallback path; for questions spanning a known topic / theme across episodes, the LLM SHOULD prefer `search_with_topic_prefilter` to avoid topic-related-but-wrong-episode chunks dominating the merged pool.
- `search_with_topic_prefilter` SHALL internally call `episode_finders.find_episodes_by_topic(show_id, [topic])` to obtain a candidate episode set, then call `rag.retrieve_hybrid` with `episode_id_filter` set to the candidate set. When the candidate set is empty, the tool SHALL fall back to `rag.retrieve_hybrid` without an episode filter (matching `search_across_episodes` behavior) so the caller still receives some chunks rather than an empty result.
- `find_episode_by_ref` SHALL call `episode_finders.find_by_ref`.
- `find_episodes_by_guest` / `find_episodes_by_topic` / `find_episodes_by_date` / `list_episodes` SHALL call the corresponding `episode_finders` functions.
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
source: retrieval-cross-episode-episode-prefilter
updated: 2026-05-26
code:
  - backend/app/services/chat_agent/tools.py
tests:
  - backend/tests/test_chat_agent_topic_prefilter.py
-->

---
### Requirement: System prompt instructs tool-eager grounded behaviour

The agent's system prompt (`chat_agent.prompts.SYSTEM_PROMPT`) SHALL contain sections that enforce tool-eager grounded behavior. The relative ordering of grounding-related sections SHALL be determined by the documented root-cause distribution (recorded in `backend/eval/results/hallucination_root_cause_distribution.json`) as follows:

1. **Role description** identifying the agent as PodcastRAG's chat agent SHALL always appear first.
2. **Tool-eager instruction** stating that the agent MUST call at least one tool before refusing or answering whenever the user asks about specific information (episode numbers, hosts, guests, content, show overview, theme, vibe) SHALL appear second. The instruction MUST explicitly include "show overview / 節目主題 / 節目在講什麼"类型查詢 as cases that require a tool call before answering — agents MUST NOT answer such queries from prior knowledge.
3. **Grounded-refusal instruction** stating that when all relevant tools return empty, the agent MUST explicitly say it cannot find X rather than fabricate, and when input schema is invalid, the agent MUST ask the user to clarify rather than guess.
4. **Fact-grounding rule** listing the six categories that MUST NEVER be fabricated (show title, host/guest name, EP number, episode title, guest quotes, statistical numbers). The relative position of this rule SHALL be:
   - If `tool_call_empty` ≥ 60% of severe hallucinations in the diagnose distribution: this rule SHALL appear immediately after the tool-eager instruction (i.e., before the tool-error-handling rule).
   - If `noise_induced` ≥ 60% of severe hallucinations: this rule SHALL include at least two `Example` blocks pairing a fabricated answer with the correct refusal template.
   - In all other cases: both the position change AND the example blocks SHALL be applied.
5. **Tool-error-handling rule** and **tool-routing hints** SHALL remain unchanged in content; only their relative position MAY shift to accommodate the grounding rule reordering.

#### Scenario: Specific-information query triggers tool call

- **GIVEN** the user asks "馬世芳上過哪一集？" (a specific information query about a guest)
- **WHEN** the agent processes the request
- **THEN** the agent SHALL call at least one tool (e.g., `find_episodes_by_guest`) before producing the final answer
- **AND** the answer SHALL NOT be a flat refusal without any tool invocation

#### Scenario: Show-overview query triggers tool call

- **GIVEN** the user asks "這節目在講什麼？" or "這個 podcast 主題是什麼？" (a show-overview / theme query)
- **WHEN** the agent processes the request
- **THEN** the agent SHALL call at least one tool (e.g., `list_episodes` to retrieve a recent episode description, or `find_show_by_name`) before producing the final answer
- **AND** the agent SHALL NOT answer from prior knowledge of the show title or theme

##### Example: show-overview tool-first behavior

- **GIVEN** the prompt explicitly lists show-overview as a tool-required category
- **WHEN** the user asks "也好吃這個 podcast 在講什麼？" (where "也好吃" does not exist in the database)
- **THEN** the agent SHALL call `find_show_by_name(name="也好吃")` (or equivalent listing tool)
- **AND** the tool SHALL return empty
- **AND** the agent SHALL reply "查不到「也好吃」這個節目" rather than fabricating a description

#### Scenario: Six-category fact grounding holds under noise

- **GIVEN** the user asks about a fact in one of the six grounded categories (show title, host/guest, EP number, episode title, quote, statistic)
- **AND** tool results return chunks that are topic-related but do not contain the specific fact
- **WHEN** the agent composes its answer
- **THEN** the agent SHALL respond with "資料不足，無法確認" or an equivalent grounded refusal
- **AND** the agent SHALL NOT infer or fabricate any value in the six categories from the noise chunks

##### Example: noise-induced refusal

- **GIVEN** the user asks "嘻哈饒舌歌唱比賽的冠軍是誰？" (chasing a guest name)
- **AND** the retrieval returns chunks about "大嘻哈時代" judges but no winner identity
- **WHEN** the agent composes its answer
- **THEN** the agent SHALL reply "節目未提及嘻哈饒舌歌唱比賽冠軍的資訊" rather than naming any judge as the winner

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

---
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

---
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

---
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

---
### Requirement: Hallucination regression SHALL trigger root-cause classification before prompt modification

When `extended-multi-turn-40.json` LLM-judge results show `hallucination_severe_count / n_turns_scored > 0.20` (i.e., regression past the baseline gate), the team SHALL run `backend/eval/scripts/classify_hallucination_root_cause.py` to produce `backend/eval/results/hallucination_root_cause_distribution.json` BEFORE modifying `SYSTEM_PROMPT`. Direct prompt edits without a corresponding distribution file SHALL be rejected at code review.

The distribution file SHALL classify each severe and mild turn into exactly one of: `tool_call_empty`, `noise_induced`, `wrong_tool_chosen`, `tool_returned_partial`. Every classified turn SHALL include an `evidence` field referencing tool_calls, tool_results, or final_answer content. No turn MAY have `root_cause = null` or an out-of-enum value.

#### Scenario: Regression triggers diagnose

- **GIVEN** a fresh LLM-judge run produces `hallucination_severe_count = 9` over 40 turns (0.225, exceeding 0.20 baseline)
- **WHEN** an engineer plans to edit `SYSTEM_PROMPT`
- **THEN** the engineer SHALL first run `classify_hallucination_root_cause.py`
- **AND** the resulting distribution JSON SHALL contain all 9 severe + all mild turns with non-null `root_cause`
- **AND** the prompt edit SHALL cite which root-cause cluster the change targets

#### Scenario: Distribution file rejects incomplete classification

- **GIVEN** the classifier returns `root_cause = null` for any turn
- **WHEN** the script writes the output JSON
- **THEN** the script SHALL exit with non-zero status
- **AND** SHALL NOT overwrite an existing distribution file with partial data

---
### Requirement: Hallucination gate for chat-agentic prompt changes

Any change that modifies `SYSTEM_PROMPT` grounding behavior SHALL re-run the agent evaluation against `extended-multi-turn-40.json` followed by the LLM judge using the same `judge_model = "gpt-4o"` and dataset. The change MAY be archived only if all three conditions hold against the new judge result:

- `hallucination_severe_count / n_turns_scored ≤ 0.10`
- `hallucination_mild_count / n_turns_scored ≤ 0.275`
- `answer_quality_mean ≥ 0.5375`

The judge result JSON SHALL include `meta.judge_model`, `meta.dataset_file`, and `meta.run_at` fields to permit later reproducibility.

#### Scenario: Gate passes

- **GIVEN** a re-judge run produces `hallucination_severe_count = 3` over 40 turns (0.075)
- **AND** `hallucination_mild_count = 9` (0.225)
- **AND** `answer_quality_mean = 0.58`
- **WHEN** the engineer requests archive
- **THEN** the change SHALL be eligible to archive

#### Scenario: Gate fails on severe

- **GIVEN** a re-judge run produces `hallucination_severe_count = 6` over 40 turns (0.15, exceeds 0.10)
- **WHEN** the engineer requests archive
- **THEN** the archive SHALL be blocked
- **AND** the team SHALL either revisit the diagnose branch or schedule a follow-up round

#### Scenario: Gate fails on quality regression

- **GIVEN** a re-judge run produces `hallucination_severe_count = 2` (passes severe gate)
- **AND** `answer_quality_mean = 0.50` (below 0.5375 baseline)
- **WHEN** the engineer requests archive
- **THEN** the archive SHALL be blocked because grounding cannot come at the cost of useful answers

---
### Requirement: Chat agent eval runner SHALL capture debug_trace into result JSON

The chat agent evaluation runner (`backend/scripts/run_chat_agent_eval.py`) SHALL pass `debug_trace=true` as a query parameter when invoking `POST /shows/{show_id}/query` for chat-mode evaluation runs. The runner SHALL persist the returned `tool_calls` (including `args` and `result_full` fields) and `trace` (including `llm_calls` and `stage_timings`) into a per-turn `trace` object in the output result JSON. The existing `tool_calls_made` field (list of tool name strings) SHALL be retained without modification for backward compatibility with consumer scripts written against earlier result files.

If the response does not include a `trace` object (for example when the session lacks admin role, or the backend is running an older build without the gate), the runner SHALL log a warning to stderr and write `null` to the per-turn `trace` field rather than failing the run.

#### Scenario: Admin session captures full tool I/O per turn

- **GIVEN** the runner is invoked with an admin session token via the `PODCASTRAG_SESSION` environment variable
- **AND** the dataset includes a turn whose chat answer triggers `find_episodes_by_date` and `search_across_episodes` tool calls
- **WHEN** the runner finishes processing that turn
- **THEN** the result JSON `turns[].trace` SHALL contain at least one `tool_calls` entry per actual tool invocation
- **AND** each `tool_calls` entry SHALL include `args` (dict of input arguments) and `result_full` (the JSON-serialised tool return value)
- **AND** the result JSON `turns[].trace.stage_timings` SHALL include all five stage timing fields documented in `AgentTraceResponse`

##### Example: shape of a captured turn

- **GIVEN** the user asks "2024 年 11 月有哪些集?" on show "這又沒有很屌"
- **AND** the agent invokes `find_episodes_by_date(show_id=..., start_date="2024-11-01", end_date="2024-11-30")`
- **WHEN** the runner writes the result file
- **THEN** `turns[].trace.tool_calls[0].name` SHALL equal "find_episodes_by_date"
- **AND** `turns[].trace.tool_calls[0].args` SHALL equal `{"show_id": "...", "start_date": "2024-11-01", "end_date": "2024-11-30"}`
- **AND** `turns[].trace.tool_calls[0].result_full` SHALL be a non-empty JSON string containing the actual tool return value

#### Scenario: Non-admin session degrades gracefully

- **GIVEN** the runner is invoked with a non-admin session token
- **WHEN** the runner finishes processing a turn
- **THEN** the result JSON `turns[].trace` SHALL be `null`
- **AND** the runner SHALL log a warning to stderr noting that debug_trace was silently denied
- **AND** the runner exit code SHALL remain 0 (degraded mode does not break the run)

#### Scenario: Backward-compatible result schema

- **GIVEN** an existing diagnose script reads `turns[].tool_calls_made` from result files produced before this change
- **WHEN** the runner writes a new result file after this change
- **THEN** `turns[].tool_calls_made` SHALL still be present and contain the same list-of-tool-name-strings shape as before
- **AND** the new `turns[].trace` field SHALL be additive

---
### Requirement: Chat agent eval runner SHALL read credentials from environment variables, not argv

The chat agent evaluation runner (`backend/scripts/run_chat_agent_eval.py`) SHALL read the session token from the `PODCASTRAG_SESSION` environment variable, NOT from a command-line argument. The runner SHALL similarly read the optional CORS origin override from `PODCASTRAG_ORIGIN` environment variable. The `--auth-token` and `--origin` command-line arguments SHALL be removed. If `PODCASTRAG_SESSION` is unset or empty, the runner SHALL exit with non-zero status and a clear error message before issuing any HTTP request.

#### Scenario: Session token via env succeeds

- **GIVEN** `PODCASTRAG_SESSION` env contains a valid admin session ID
- **WHEN** the runner is invoked
- **THEN** the runner SHALL proceed with the eval run
- **AND** the session value SHALL NOT appear in `argv` (verifiable via `ps -ef` or `/proc/<pid>/cmdline` while the runner is alive)

#### Scenario: Missing env exits cleanly

- **GIVEN** `PODCASTRAG_SESSION` env is unset
- **WHEN** the runner is invoked
- **THEN** the runner SHALL exit with non-zero status before sending any HTTP request
- **AND** SHALL print a message to stderr referencing the env var name

---
### Requirement: find_episode_by_ref SHALL match episode references on word boundaries

The `find_by_ref` SQL helper (`backend/app/services/episode_finders.py::find_by_ref`) SHALL match episode references on word boundaries, NOT on substring containment. When the user reference normalises to episode number `n` (extracted via the `(?:EP|ep|第)\s*(\d+)\s*(?:集)?` regex), the SQL SHALL match titles where the token `EP{n}` or `第{n}集` appears as a standalone token — meaning the character immediately after `{n}` MUST NOT be another digit. The previous `title ILIKE '%EP{n}%'` substring match SHALL be removed.

#### Scenario: EP1 reference resolves to EP1, not EP10/100/146

- **GIVEN** the database contains episodes titled "EP1｜...", "EP10｜...", "EP100｜...", "EP146｜..." in the same show
- **WHEN** the runner calls `find_by_ref(show_id, ref='EP1')`
- **THEN** the returned episode SHALL be the EP1 episode (or `None` if no EP1 exists in this show)
- **AND** the returned episode SHALL NOT be EP10, EP100, or EP146

##### Example: EP1 vs EP146 prod regression case

- **GIVEN** show "這又沒有很屌" contains EP146 titled "EP146｜你們是不是怕沒話聊？Ft. 9m88" (published 2026-05-20) but no EP1 episode
- **WHEN** the agent calls `find_episode_by_ref(ref='EP1')`
- **THEN** the tool SHALL return `None` (or a `{"ok": false, "kind": "not_found"}` envelope)
- **AND** the tool SHALL NOT return EP146

#### Scenario: EP10 reference still resolves correctly

- **GIVEN** the database contains EP10 and EP100 in the same show
- **WHEN** the runner calls `find_by_ref(show_id, ref='EP10')`
- **THEN** the returned episode SHALL be EP10
- **AND** SHALL NOT be EP100

#### Scenario: Chinese ordinal reference resolves correctly

- **GIVEN** the database contains an episode titled "第3集｜...the show theme..."
- **WHEN** the runner calls `find_by_ref(show_id, ref='第3集')`
- **THEN** the returned episode SHALL be that 第3集 episode

---
### Requirement: Agent loop SHALL log last_enumeration_episodes state at build_messages time under admin debug_trace

When the admin `?debug_trace=true` gate is active, `_build_system_message` (`backend/app/services/chat_agent/memory.py`) SHALL emit a record into the response trace (under a new field on the existing trace structure) capturing the current `state.last_enumeration_episodes` UUID list and the `state.last_enumeration_at` timestamp at the moment the system message is built for the current turn. The record SHALL include the turn's user question for cross-reference with the dataset. When the gate is NOT active, no logging SHALL occur — the response shape and prompt content SHALL be unchanged for normal users.

This requirement creates observability ONLY; it does NOT modify the writeback, persistence, or instruction logic governing ordinal carry. The downstream fix to ordinal carry will land in a separate change once telemetry pinpoints the failing layer.

#### Scenario: Admin trace exposes state at build time

- **GIVEN** an admin session opens a multi-turn dialog and turn 1's enumeration tool populated `state.last_enumeration_episodes` with three UUIDs
- **WHEN** turn 2 issues `POST /shows/{id}/query?debug_trace=true` with question "第三集是什麼內容?"
- **THEN** the response trace SHALL include a record with the three UUIDs (in turn 1's order) and a non-null timestamp
- **AND** the record SHALL include the literal user question "第三集是什麼內容?"

#### Scenario: Non-admin session sees no state log

- **GIVEN** a non-admin session opens the same multi-turn dialog
- **WHEN** turn 2 issues `POST /shows/{id}/query?debug_trace=true`
- **THEN** the response SHALL NOT contain the state log field
- **AND** the prompt content built by `_build_system_message` SHALL be identical to a request without the query param

---
### Requirement: System prompt SHALL refuse to fabricate host roster changes

The `SYSTEM_PROMPT` constant in `backend/app/services/chat_agent/prompts.py` SHALL include a rule that forbids the agent from inferring or fabricating host roster changes ("主持人陣容變化 / 嘉賓輪替 / 主持人變動歷史" or English equivalents) from episode listings or show overview. The rule SHALL state that unless a tool result explicitly contains text marking a host change in a specific episode, the agent MUST reply with an honest refusal (e.g., "資料庫無主持人變動紀錄") rather than infer a roster timeline from `list_episodes` or `get_show_overview` output.

#### Scenario: Host change query without host_history tool returns honest refusal

- **GIVEN** the user asks "《這又沒有很屌》從第一集到現在，主持人陣容有什麼變化?"
- **AND** no tool result returned to the agent contains explicit host-change marker text
- **WHEN** the agent composes its answer
- **THEN** the answer SHALL contain an honest refusal phrase indicating no host change record is available
- **AND** the answer SHALL NOT list specific host names with implied roster changes (e.g., "初期是 X、後期是 Y")

##### Example: refusal phrasing

- **GIVEN** the user asks the host-roster-change question above
- **WHEN** the agent answers
- **THEN** the answer SHALL include text equivalent to "目前資料庫沒有節目主持人變動的明確紀錄，無法回答主持陣容變化"

---
### Requirement: Agent answers SHALL flag unverified EP references and quoted strings

Before the agent loop returns a final chat answer to the API layer, the answer text SHALL be scanned against the concatenation of all `tool_calls[].result_full` strings collected during this turn. The scan SHALL apply two regex passes:

1. Every `EP\d+` token in the answer SHALL appear as a substring in the concatenated reference text.
2. Every quoted string enclosed in CJK quotes (`「...」`) or ASCII double quotes (`"..."`) of at least 4 characters SHALL appear as a substring in the concatenated reference text.

Any unmatched token SHALL be **annotated** in-place by appending the suffix `[未驗證]` immediately after the token, **not stripped**. The response object SHALL expose an `unverified_count` integer field on the `ChatResponse` schema indicating how many tokens were annotated (zero when none).

#### Scenario: Real EP reference is not annotated

- **GIVEN** the agent's tool calls returned a `find_episodes_by_date` result containing `"title": "EP69｜Demo徵集2..."`
- **AND** the agent's final answer contains the substring "EP69"
- **WHEN** the post-generation scan runs
- **THEN** the answer SHALL NOT have `[未驗證]` appended after "EP69"
- **AND** `unverified_count` SHALL be 0 for this token

##### Example: b12 partial-fabrication case after fix

- **GIVEN** the agent calls `find_episodes_by_date(start="2024-11-01", end="2024-11-30")` and the tool returns one episode EP69
- **AND** the agent's answer contains "EP69｜Demo徵集2..." and also fabricates "EP70｜...", "EP71｜..."
- **WHEN** the post-generation scan runs
- **THEN** "EP69" SHALL NOT be annotated
- **AND** "EP70" SHALL be followed by "[未驗證]"
- **AND** "EP71" SHALL be followed by "[未驗證]"
- **AND** `unverified_count` SHALL be 2

#### Scenario: Fabricated quote is annotated

- **GIVEN** the agent's tool calls returned chunks NOT containing the string "我覺得這就是安身之處"
- **AND** the agent's final answer contains `「我覺得這就是安身之處」`
- **WHEN** the post-generation scan runs
- **THEN** the answer SHALL have `[未驗證]` appended after the closing quote
- **AND** `unverified_count` SHALL be at least 1

#### Scenario: Short quoted strings are not scanned

- **GIVEN** the agent's answer contains `「好」` (3 characters or fewer)
- **WHEN** the post-generation scan runs
- **THEN** the short quote SHALL NOT be checked or annotated

---
### Requirement: Episode reference resolver SQL SHALL NOT collide with SQLAlchemy bind syntax

The `find_by_ref` resolver in `backend/app/services/episode_finders.py` SHALL NOT use PCRE non-capturing groups (`(?:...)`) inside SQL text passed to `sqlalchemy.text()`, because SQLAlchemy parses any `:identifier` token (including `:EP`, `:集` embedded inside `(?:EP|第)` / `(?:集)?`) as a bind parameter placeholder and raises `StatementError: A value is required for bind parameter 'EP'` at execute time. Equivalent boolean-match semantics SHALL be obtained by using plain capturing groups (`(EP|第)`, `(集)?`) instead, since the `title ~*` operator returns only a boolean and never references capture group output.

#### Scenario: find_by_ref resolves EP-number reference without raising

- **GIVEN** an episode with title containing `EP143` exists in the show
- **WHEN** the agent calls `find_episode_by_ref(ref="EP143")`
- **THEN** `find_by_ref` SHALL execute the EP-number SQL without raising `StatementError`
- **AND** SHALL return an `EpisodeRef` whose `episode_id` matches the episode

#### Scenario: find_by_ref resolves Chinese ordinal reference without raising

- **GIVEN** an episode with title containing `EP19` exists in the show
- **WHEN** the agent calls `find_episode_by_ref(ref="第19集")`
- **THEN** `find_by_ref` SHALL execute the EP-number SQL without raising `StatementError`
- **AND** SHALL return the same `EpisodeRef` as `find_episode_by_ref(ref="EP19")` would

#### Scenario: find_by_ref returns None for unmatched EP-number

- **GIVEN** no episode with title containing `EP999` exists in the show
- **WHEN** the agent calls `find_episode_by_ref(ref="EP999")`
- **THEN** `find_by_ref` SHALL execute the EP-number SQL without raising
- **AND** SHALL fall back to the title-ILIKE SQL
- **AND** SHALL return `None` when both queries find no row

#### Scenario: SQL string contains no PCRE non-capturing group syntax

- **GIVEN** the `_BY_REF_EP_NUMBER_SQL` constant in `backend/app/services/episode_finders.py`
- **WHEN** a regression test asserts on the SQL string
- **THEN** the SQL string SHALL NOT contain the substring `(?:`
- **AND** the SQL string SHALL still match an episode title containing `EP143` when executed against a row whose `title` is `EP143｜某集標題`

<!-- @trace
source: episode-ref-sql-bug-fix
updated: 2026-05-25
code:
  - backend/app/services/episode_finders.py
  - docs/eval-strategy.md
tests:
  - backend/tests/services/test_episode_finders_by_ref.py
-->

---
### Requirement: find_episode_by_ref SHALL auto-pin resolved episode to session focused state

When the agent invokes `find_episode_by_ref(ref=...)` and the underlying `episode_finders.find_by_ref` call returns a non-None `EpisodeRef`, the tool dispatcher SHALL write the resolved `episode_id` into `ChatSessionState.focused_episode_id` AND SHALL set `ChatSessionState.focused_episode_at` to the current UTC timestamp, BEFORE returning the tool result to the LLM. The tool result envelope returned to the LLM SHALL include an `auto_pinned: true` field so the LLM can observe that the episode is now in session focus. When the resolver returns None (no episode matched), session state SHALL NOT be modified and the envelope SHALL contain `auto_pinned: false`.

#### Scenario: Resolved episode is auto-pinned

- **GIVEN** an empty `ChatSessionState` with `focused_episode_id = None`
- **AND** the agent calls `find_episode_by_ref(ref="EP143")` which resolves to episode `<EP143-uuid>`
- **WHEN** the tool dispatcher records the result
- **THEN** `ChatSessionState.focused_episode_id` SHALL be set to `<EP143-uuid>`
- **AND** `ChatSessionState.focused_episode_at` SHALL be set to the current UTC timestamp
- **AND** the tool result envelope SHALL contain `auto_pinned: true`
- **AND** the state SHALL be persisted to Redis with TTL refreshed

#### Scenario: Failed resolution does not modify session state

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <existing-uuid>`
- **AND** the agent calls `find_episode_by_ref(ref="EP9999")` which returns None
- **WHEN** the tool dispatcher records the result
- **THEN** `ChatSessionState.focused_episode_id` SHALL remain `<existing-uuid>`
- **AND** the tool result envelope SHALL contain `auto_pinned: false`

#### Scenario: Auto-pin overwrites prior focused episode

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP140-uuid>` (set by an earlier turn's auto-pin)
- **AND** the agent in the current turn calls `find_episode_by_ref(ref="EP19")` which resolves to `<EP19-uuid>`
- **WHEN** the tool dispatcher records the result
- **THEN** `ChatSessionState.focused_episode_id` SHALL be overwritten to `<EP19-uuid>`
- **AND** `ChatSessionState.focused_episode_at` SHALL be updated to the current UTC timestamp


<!-- @trace
source: multi-turn-epref-resolution-fix
updated: 2026-05-26
code:
  - backend/app/services/chat_agent/tools.py
tests:
  - backend/tests/test_chat_agent_epref_carry.py
-->

---
### Requirement: Episode-scoped tools SHALL fall back to session focused_episode_id when episode_id arg is omitted

The tools `search_within_episode`, `get_episode_segments`, and `get_episode_summary` (which all require an `episode_id` to scope their query) SHALL, in their dispatcher pre-processing step, check whether the LLM provided a non-empty `episode_id` argument:

- If `episode_id` is provided explicitly and non-empty, the dispatcher SHALL use it as-is. The tool result envelope SHALL include `episode_id_source: "explicit"`.
- If `episode_id` is omitted or empty AND `ChatSessionState.focused_episode_id` is non-None, the dispatcher SHALL substitute `ChatSessionState.focused_episode_id` as the effective `episode_id` before invoking the underlying service. The tool result envelope SHALL include `episode_id_source: "session_focused"` AND `effective_episode_id: <uuid>`.
- If both are absent, the dispatcher SHALL return an error envelope with `episode_id_source: "missing"` and a `user_hint` describing that no episode is in focus and the LLM should call `find_episode_by_ref` first.

#### Scenario: Explicit episode_id is preserved

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP143-uuid>`
- **AND** the agent calls `search_within_episode(query="家常味", episode_id="<EP140-uuid>")`
- **WHEN** the tool dispatcher pre-processes the call
- **THEN** the underlying retrieve call SHALL use `<EP140-uuid>` (NOT the session focused id)
- **AND** the tool result envelope SHALL contain `episode_id_source: "explicit"`

#### Scenario: Omitted episode_id falls back to session focused

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP143-uuid>` from a prior auto-pin
- **AND** the agent calls `search_within_episode(query="RAG")` without an `episode_id` argument
- **WHEN** the tool dispatcher pre-processes the call
- **THEN** the underlying retrieve call SHALL use `<EP143-uuid>` (substituted from session)
- **AND** the tool result envelope SHALL contain `episode_id_source: "session_focused"` AND `effective_episode_id: "<EP143-uuid>"`

#### Scenario: Both missing returns guided error envelope

- **GIVEN** a `ChatSessionState` with `focused_episode_id = None`
- **AND** the agent calls `get_episode_segments()` without an `episode_id` argument
- **WHEN** the tool dispatcher pre-processes the call
- **THEN** the underlying service SHALL NOT be invoked
- **AND** the tool result envelope SHALL contain `episode_id_source: "missing"` AND a `user_hint` string instructing the LLM to call `find_episode_by_ref` first

#### Scenario: Fallback applies to get_episode_summary

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP140-uuid>`
- **AND** the agent calls `get_episode_summary()` without an `episode_id` argument in a follow-up turn
- **WHEN** the tool dispatcher pre-processes the call
- **THEN** the underlying summary service SHALL be invoked with `<EP140-uuid>`
- **AND** the tool result envelope SHALL contain `episode_id_source: "session_focused"`


<!-- @trace
source: multi-turn-epref-resolution-fix
updated: 2026-05-26
code:
  - backend/app/services/chat_agent/tools.py
tests:
  - backend/tests/test_chat_agent_epref_carry.py
-->

---
### Requirement: pin_episode SHALL be idempotent when target episode is already focused

The `pin_episode(episode_id=X)` tool SHALL succeed without raising an error when `ChatSessionState.focused_episode_id` already equals `X` (e.g., because an earlier `find_episode_by_ref` already auto-pinned X). In this idempotent path the tool result envelope SHALL contain `ok: true` AND `already_pinned: true` so the LLM can distinguish "newly pinned" from "no-op". When `focused_episode_id` is None or differs from X, `pin_episode` SHALL proceed with the standard write (existing behavior) and the envelope SHALL contain `ok: true` AND `already_pinned: false`.

#### Scenario: Pin to currently-focused episode is a no-op

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP143-uuid>` (auto-pinned earlier)
- **AND** the agent calls `pin_episode(episode_id="<EP143-uuid>")`
- **WHEN** the tool dispatcher processes the call
- **THEN** the tool result envelope SHALL contain `ok: true` AND `already_pinned: true`
- **AND** `ChatSessionState.focused_episode_at` MAY be refreshed to the current UTC timestamp (but otherwise no state change)
- **AND** no error or warning SHALL be raised to the LLM

#### Scenario: Pin to different episode performs normal write

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP143-uuid>`
- **AND** the agent calls `pin_episode(episode_id="<EP140-uuid>")`
- **WHEN** the tool dispatcher processes the call
- **THEN** `ChatSessionState.focused_episode_id` SHALL be updated to `<EP140-uuid>`
- **AND** the tool result envelope SHALL contain `ok: true` AND `already_pinned: false`

#### Scenario: Pin from empty state performs normal write

- **GIVEN** a `ChatSessionState` with `focused_episode_id = None`
- **AND** the agent calls `pin_episode(episode_id="<EP19-uuid>")`
- **WHEN** the tool dispatcher processes the call
- **THEN** `ChatSessionState.focused_episode_id` SHALL be set to `<EP19-uuid>`
- **AND** the tool result envelope SHALL contain `ok: true` AND `already_pinned: false`

<!-- @trace
source: multi-turn-epref-resolution-fix
updated: 2026-05-26
code:
  - backend/app/services/chat_agent/tools.py
tests:
  - backend/tests/test_chat_agent_epref_carry.py
-->

---
### Requirement: search_with_topic_prefilter SHALL pre-scope retrieval to topic-matching episodes

The `search_with_topic_prefilter(topic: str, query: str, k: int = 5)` tool SHALL execute the following retrieval pipeline:

1. Call `episode_finders.find_episodes_by_topic(show_id, [topic])` to obtain a candidate episode list `candidates`.
2. If `len(candidates) > 0`, call `rag.retrieve_hybrid(query, episode_id_filter=[ep.episode_id for ep in candidates], k=30)` to obtain a candidate chunk pool, then invoke `rag_rerank.voyage_rerank(question=query, chunks=pool, k=k)` to reorder by relevance and return the top `k`. The rerank stage SHALL use the Voyage `rerank-2.5` model via the `voyageai` Python SDK with credentials read from the `VOYAGE_API_KEY` environment variable.
3. If `len(candidates) == 0`, fall back to `rag.retrieve_hybrid(query, k=k)` without filter and skip rerank (return directly with `rerank_applied=false / rerank_input_count=0`).
4. When the rerank call fails (timeout exceeding 3.0s, non-2xx response, malformed response, or output references indices absent from the candidate pool), the tool SHALL fall back to the original RRF order of the top `k` chunks from the candidate pool and SHALL set `rerank_applied=false`. Unknown indices in the Voyage output SHALL be discarded; if fewer than `k` valid chunks remain, the gap SHALL be filled from the original RRF order.

The tool result envelope SHALL include:

- `chunks`: same shape as other search tools (list of dicts via `_chunk_to_dict`)
- `prefilter_episode_count`: integer, the size of `candidates` returned by the topic finder
- `fallback_to_full_pool`: boolean, `true` when the empty-candidate fallback path was taken, `false` when the prefilter path ran
- `rerank_applied`: boolean, `true` when Voyage rerank successfully returned a usable ranking, `false` otherwise (including the empty-candidate fallback path)
- `rerank_input_count`: integer, the number of chunks sent to the rerank stage (`len(pool)`, which is at most 30 and may be smaller when the prefilter pool has fewer than 30 chunks). When the empty-candidate fallback path was taken, this field SHALL be `0`.

#### Scenario: Topic match returns candidates, retrieval is scoped to them

- **GIVEN** the show contains episodes EP143, EP107, EP66 whose `find_episodes_by_topic(topic="家常味")` returns `[EP143, EP107]`
- **AND** the LLM calls `search_with_topic_prefilter(topic="家常味", query="馬世芳怎麼定義家常味", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL pass `episode_id_filter=[EP143_uuid, EP107_uuid]` and `k=30`
- **AND** Voyage rerank SHALL be invoked with the 30-chunk pool
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `2`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `false`
- **AND** the envelope's `rerank_applied` SHALL be `true` on rerank success
- **AND** the envelope's `rerank_input_count` SHALL equal `30`
- **AND** no returned chunk SHALL have an `episode_id` outside `{EP143_uuid, EP107_uuid}`

#### Scenario: No topic match falls back to full-show retrieval without filter

- **GIVEN** `find_episodes_by_topic(topic="lorem-ipsum-no-match")` returns an empty list
- **AND** the LLM calls `search_with_topic_prefilter(topic="lorem-ipsum-no-match", query="any question", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL be invoked WITHOUT an `episode_id_filter` (full show pool) and with `k=5` (no top-N expand)
- **AND** Voyage rerank SHALL NOT be invoked
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `0`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `true`
- **AND** the envelope's `rerank_applied` SHALL be `false`
- **AND** the envelope's `rerank_input_count` SHALL be `0`
- **AND** `chunks` MAY contain up to `k` results spanning any episode

#### Scenario: Envelope fields are always populated

- **GIVEN** any successful invocation of `search_with_topic_prefilter`
- **WHEN** the tool dispatcher records the result
- **THEN** the envelope SHALL contain the keys `chunks`, `prefilter_episode_count`, `fallback_to_full_pool`, `rerank_applied`, and `rerank_input_count` regardless of whether the prefilter path, fallback path, or rerank failure path executed
- **AND** the chunk dict shape SHALL be identical to that returned by `search_across_episodes` and `search_in_episodes` (so downstream `_collect_agentic_citations` does not need branching)

#### Scenario: Tool description guides LLM away from search_across_episodes for topical questions

- **GIVEN** the OpenAI tool schema generated from `SearchWithTopicPrefilterInput`
- **WHEN** the schema is rendered to the LLM
- **THEN** the description string SHALL explicitly recommend this tool over `search_across_episodes` for questions that name a topic / theme spanning multiple episodes
- **AND** the `search_across_episodes` tool description SHALL be updated to call itself the "fallback" path and refer the LLM to `search_with_topic_prefilter` for topical cross-episode queries

#### Scenario: Voyage rerank reorders the candidate pool

- **GIVEN** prefilter path produced a 30-chunk candidate pool from `retrieve_hybrid`
- **AND** Voyage `rerank-2.5` returns relevance scores ordering chunk 13 first, chunk 5 second, chunk 1 third
- **WHEN** the tool collects the top `k=5` chunks
- **THEN** the returned `chunks` SHALL be ordered according to Voyage's ranking (chunks 13, 5, 1 in positions 1-3, then 4th and 5th positions from Voyage's ranking)
- **AND** the envelope's `rerank_applied` SHALL be `true`
- **AND** the envelope's `rerank_input_count` SHALL equal `30`

#### Scenario: Voyage rerank failure falls back to original RRF order

- **GIVEN** prefilter path produced a 30-chunk candidate pool
- **WHEN** the Voyage rerank call times out (exceeds 3.0s), returns non-2xx, returns malformed response, or the `VOYAGE_API_KEY` environment variable is unset
- **THEN** the tool SHALL return the first `k` chunks of the original RRF order
- **AND** the envelope's `rerank_applied` SHALL be `false`
- **AND** the envelope's `rerank_input_count` SHALL still report the actual number of chunks sent to (or that would have been sent to) rerank (e.g., `30`)
- **AND** no exception SHALL propagate to the agent loop

#### Scenario: Voyage rerank output partially unknown indices are filtered and back-filled

- **GIVEN** prefilter path produced a 30-chunk candidate pool
- **AND** the Voyage rerank response includes indices outside `[0, 29]` (e.g., due to API contract drift)
- **WHEN** the tool collects the top `k=5` chunks
- **THEN** unknown indices SHALL be discarded
- **AND** the kept ordering SHALL follow valid indices in Voyage's order
- **AND** the gap (if fewer than `k` valid) SHALL be filled from the next chunk in original RRF order that is not already in the kept list
- **AND** the envelope's `rerank_applied` SHALL be `true`

<!-- @trace
source: retrieval-rerank-via-voyage
updated: 2026-05-27
code:
  - backend/app/services/chat_agent/tools.py
  - backend/app/services/rag_rerank.py
tests:
  - backend/tests/test_chat_agent_topic_prefilter_rerank.py
  - backend/tests/test_voyage_rerank.py
note: supersedes the LLM-as-reranker pipeline introduced (and disabled) by
      change retrieval-cross-episode-chunk-recovery. The envelope contract
      (rerank_applied, rerank_input_count) is reused intact.
-->

---
### Requirement: `find_episodes_by_topic` SHALL dispatch to a guest-index path when topic tokens match known guest names

When `find_episodes_by_topic(show_id, topic_terms)` receives a `topic_terms` list whose tokens (after the existing jieba tokenisation) contain at least two members that exist in the show's set of known guest names (collected by scanning `episodes.guests` JSONB string-array column), the function SHALL execute a guest-index SQL path **in addition to** the existing title / description tsquery path and SHALL return the union (deduplicated) of both result sets.

The guest-index SQL path SHALL match episodes whose `episodes.guests` JSONB string-array contains at least one entry equal to (case-sensitive) any of the matched guest tokens. The returned list SHALL preserve the existing `ORDER BY e.published_at DESC NULLS LAST` semantics.

When fewer than two tokens match known guest names, the function SHALL behave identically to its prior implementation (title / description tsquery only). The fallback contract for empty `topic_terms` SHALL remain unchanged (returns `[]`).

#### Scenario: Two guest tokens trigger guest-index dispatch

- **GIVEN** the show has episode A with `guests=["Leo 王"]` and episode B with `guests=["小老虎","Leo 王"]`
- **AND** episode C has `guests=[]` but its title contains the string "Leo"
- **WHEN** `find_episodes_by_topic(show_id, ["迪拉 Leo 王"])` is invoked
- **THEN** the jieba-tokenised topic resolves to tokens including `"迪拉"`, `"Leo"`, `"王"`
- **AND** because `"Leo"` and `"王"` (or `"Leo 王"` after a single-string match) appear in the show's known-guest set in at least two distinct guest entries
- **THEN** the function SHALL run the guest-index SQL path
- **AND** the returned list SHALL include episode A and episode B
- **AND** the returned list MAY include episode C if the existing title tsquery path also matched

#### Scenario: Single guest token preserves prior behaviour

- **GIVEN** the show has episode A with `guests=["馬世芳"]`
- **WHEN** `find_episodes_by_topic(show_id, ["馬世芳的家常味"])` is invoked
- **AND** only one token (`"馬世芳"`) matches the known-guest set after tokenisation
- **THEN** the function SHALL NOT execute the guest-index SQL path
- **AND** SHALL return the same result as the prior implementation (title / description tsquery only)

#### Scenario: No guest tokens preserve prior behaviour

- **GIVEN** the topic terms `["家常味"]` contain no tokens matching any known guest name
- **WHEN** `find_episodes_by_topic` is invoked
- **THEN** the function SHALL execute only the existing title / description tsquery path


<!-- @trace
source: b23-dataset-and-retrieval-rca-fix
updated: 2026-05-27
code:
  - docs/roadmap.md
  - src/releaseLog.jsx
-->

---
### Requirement: `search_with_topic_prefilter` envelope SHALL expose `prefilter_source` for observability

The `search_with_topic_prefilter` tool's response envelope SHALL include a `prefilter_source` field whose value is one of the strings `"topic_index"`, `"guest_index"`, or `"merged"`. The field SHALL reflect which internal dispatch path produced the candidate episode set.

When the candidate set comes solely from the prior title / description tsquery path, `prefilter_source` SHALL be `"topic_index"`. When the candidate set comes solely from the guest-index SQL path (i.e., the title path returned no candidates), `prefilter_source` SHALL be `"guest_index"`. When both paths contributed, `prefilter_source` SHALL be `"merged"`.

When the candidate set is empty and the tool falls back to `rag.retrieve_hybrid` without `episode_id_filter`, `prefilter_source` SHALL still be set to the path that was attempted (defaulting to `"topic_index"` when neither path matched), and `fallback_to_full_pool` SHALL remain `true`.

#### Scenario: Guest-index path triggers `prefilter_source=guest_index`

- **GIVEN** the LLM invokes `search_with_topic_prefilter(topic="迪拉 Leo 王", query="第一次見面的故事")`
- **AND** `find_episodes_by_topic` returns candidates only via the guest-index path (title tsquery returned empty)
- **WHEN** the tool builds its response envelope
- **THEN** the envelope SHALL include `"prefilter_source": "guest_index"`
- **AND** `prefilter_episode_count` SHALL reflect the guest-path candidate count

#### Scenario: Merged path triggers `prefilter_source=merged`

- **GIVEN** both the title path and the guest-index path contribute distinct candidate episodes
- **WHEN** `find_episodes_by_topic` returns the union
- **THEN** the envelope SHALL include `"prefilter_source": "merged"`

#### Scenario: Topic-only path preserves prior envelope shape semantics

- **GIVEN** a query without any guest-name token
- **WHEN** the tool runs the existing title / description tsquery only
- **THEN** the envelope SHALL include `"prefilter_source": "topic_index"`
- **AND** all other existing envelope fields (`prefilter_episode_count`, `fallback_to_full_pool`, `rerank_applied`, `rerank_input_count`) SHALL retain their prior semantics

<!-- @trace
source: b23-dataset-and-retrieval-rca-fix
updated: 2026-05-27
code:
  - docs/roadmap.md
  - src/releaseLog.jsx
-->

---
### Requirement: Answer-step model must honor forced tool_choice with the full tool spec

The model configured for the `answer` AI step (`ai_steps.answer.model`) SHALL honor OpenAI forced `tool_choice` (a specific `{"type":"function","function":{"name":...}}` selection) when called with the full chat-agent tool spec (`OPENAI_TOOLS_SPEC`, currently 14 tools). This is a precondition for the deterministic first-turn routing nudge (b22 `search_with_topic_prefilter` force) to take effect. Any change to `ai_steps.answer.model` SHALL be validated against this requirement before it is relied upon for routing, because some models (verified: gpt-4o, gpt-4.1-mini via AI Hub) silently ignore forced `tool_choice` under the full spec and fall back to free tool selection, while others (verified: gpt-4.1, gpt-5.1, gemini-2.5-flash, gemini-2.5-pro) honor it.

#### Scenario: Configured answer model honors forced tool_choice

- **GIVEN** `ai_steps.answer.model` is set to the selected model
- **AND** a cross-episode topical question (b23) that the routing detector flags for force
- **WHEN** the chat agent's first LLM call passes `tool_choice` forcing `search_with_topic_prefilter` with the full tool spec
- **THEN** the trace's first tool call SHALL be `search_with_topic_prefilter`

> Note: whether the answer ultimately cites EP107 is NOT part of this requirement.
> The 2026-06-07 bake-off proved EP107 surfacing is bounded by the lexical
> topic-prefilter mechanism (entity-token flooding pushes EP107 out of the
> `ts_rank` cap), independent of the answer model — verified gpt-5.1 0/4 and
> gemini-2.5-pro 1/4 even with correct routing. EP107 reliability is owned by the
> `topic-prefilter-transcript-aware` capability and its follow-up (semantic
> episode selection / entity-token stripping), not by the answer-step model.

#### Scenario: Answer model that ignores forced tool_choice is rejected for routing

- **GIVEN** a candidate model is evaluated for the `answer` step
- **WHEN** it is called with the full tool spec and a forced `tool_choice` for a specific function
- **AND** it returns a different (freely chosen) tool instead of the forced one
- **THEN** that model SHALL NOT be selected as the `answer` step model while b22 deterministic routing is relied upon

<!-- @trace
source: answer-model-bakeoff-and-switch
updated: 2026-06-07
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/answer_model_bakeoff.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/b23_prod_smoke.sh
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
-->

---
### Requirement: Topic candidate selection includes transcript-chunk matches

The system SHALL include transcript-chunk matches as a candidate source when `find_episodes_by_topic` / `find_episodes_by_topic_with_source` selects candidate episodes. An episode SHALL be a candidate when it matches the topic tsquery via its title, any of its description chunks, OR any of its transcript chunks. The transcript-chunk source SHALL be controlled by a default-on boolean setting `enable_transcript_topic_prefilter`; when the setting is `False`, candidate selection SHALL be bit-equivalent to the prior title-plus-description behavior. The recency-listing topic filter (`find_episodes_by_recency`) is out of scope for this requirement and retains the prior title-plus-description behavior.

#### Scenario: Transcript-buried answer episode becomes a candidate

- **WHEN** a topic's discriminating tokens appear in an episode's transcript chunks but not in its title or description
- **AND** `enable_transcript_topic_prefilter` is `True`
- **THEN** that episode SHALL be included in the candidate set returned by `find_episodes_by_topic`

#### Scenario: Flag off preserves prior behavior

- **WHEN** `enable_transcript_topic_prefilter` is `False`
- **THEN** candidate selection SHALL match the prior title-plus-description-chunk behavior with no transcript-chunk source


<!-- @trace
source: topic-prefilter-transcript-aware
updated: 2026-06-07
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/app/core/config.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/b22_routing_probe.py
  - backend/scripts/b23_prod_smoke.sh
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/app/services/chat_agent/routing.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/app/services/episode_finders.py
  - backend/scripts/answer_model_bakeoff.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - skills-lock.json
  - backend/app/services/chat_agent/agent.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
tests:
  - backend/tests/test_chat_agent_topic_routing_nudge.py
  - backend/tests/test_episode_finders_transcript_aware.py
  - backend/tests/test_episode_finders.py
-->

---
### Requirement: Transcript candidate source is guarded against non-discriminative over-selection

The system SHALL guard the transcript-chunk candidate source so a single common token (for example a host name appearing across most episodes) cannot select the entire show. The transcript-chunk source SHALL be applied only when the effective topic tokens number at least two after the existing jieba length filter, topic stop-words, and show-name-term removal.

The effective topic tokens SHALL be derived as follows so that the agent placing only a single entity in the `topic` argument (while the discriminating content sits in the `query` argument) does not silently disable the transcript source:

- Let `topic_tokens` be the discriminating tokens of the `topic` argument.
- WHEN `topic_tokens` has at least two tokens, the effective topic tokens SHALL be exactly `topic_tokens` (the `query` argument SHALL NOT influence selection, preserving prior behavior for focused topics).
- WHEN `topic_tokens` has fewer than two tokens AND a non-empty `query` argument is provided, the effective topic tokens SHALL be the discriminating tokens of the combined `topic` and `query` text, deduplicated.
- Otherwise the effective topic tokens SHALL be `topic_tokens`.

The OR-tsquery and the coverage arm's per-token array SHALL both be built from the same effective topic tokens. The system SHALL contribute episodes from the transcript source as the union of two capped arms, deduplicated by episode id:

1. a `ts_rank` arm — the top `transcript_prefilter_cap` episodes ranked by best transcript-chunk `ts_rank` over the topic OR-tsquery (this preserves single-token-relevant episodes for breadth-oriented topics); and
2. a coverage arm — the top `transcript_prefilter_cap` episodes ranked by the count of DISTINCT topic tokens matched in their transcript chunks, with the sum of per-token best `ts_rank` as the tie-break (this surfaces narrative episodes that cover multiple topic tokens but whose single best `ts_rank` is diluted by common tokens).

The combined contribution is therefore at most `2 × transcript_prefilter_cap` episodes. The guard SHALL NOT depend on a host registry, which does not exist; a host name is not necessarily present in the show title. When the transcript source is not applied (flag off, or fewer than two effective topic tokens), candidate selection SHALL be bit-equivalent to the prior title-plus-description behavior. The `query`-fallback derivation SHALL be governed by the same `enable_transcript_topic_prefilter` setting; no additional setting is introduced.

#### Scenario: Single token does not trigger transcript source

- **WHEN** a topic reduces to fewer than two tokens after filtering
- **AND** no `query` argument is provided (or it also yields fewer than two combined discriminating tokens)
- **THEN** the transcript-chunk candidate source SHALL NOT be applied
- **AND** candidate selection SHALL match the prior title-plus-description-chunk behavior

#### Scenario: Thin topic plus discriminating query triggers transcript source

- **GIVEN** a `topic` argument that yields fewer than two discriminating tokens (for example a single entity name)
- **AND** a `query` argument whose combined discriminating tokens with the topic number at least two
- **WHEN** `enable_transcript_topic_prefilter` is `True`
- **THEN** the transcript-chunk candidate source SHALL be applied using the combined discriminating tokens
- **AND** the OR-tsquery and the coverage arm's per-token array SHALL both be built from those combined tokens

#### Scenario: Focused topic ignores query

- **GIVEN** a `topic` argument that yields at least two discriminating tokens
- **WHEN** the transcript source is applied
- **THEN** the effective topic tokens SHALL equal the topic's discriminating tokens
- **AND** the `query` argument SHALL NOT change which episodes are selected

#### Scenario: Transcript source contributes the union of ts_rank and coverage arms

- **WHEN** more than `transcript_prefilter_cap` episodes match the topic via transcript chunks
- **THEN** the transcript source SHALL contribute the union of (the top `transcript_prefilter_cap` episodes by best transcript-chunk `ts_rank`) and (the top `transcript_prefilter_cap` episodes by distinct-token coverage with sum-of-per-token-`ts_rank` tie-break)
- **AND** the contributed set SHALL be deduplicated by episode id

#### Scenario: Narrative GT episode surfaces without dropping single-token enumeration episodes

- **GIVEN** a topic with multiple discriminating tokens where the answer episode's transcript covers most of the tokens but its single best `ts_rank` is outranked by episodes heavy in one common token
- **WHEN** the transcript source is applied
- **THEN** the multi-token-covering answer episode SHALL be contributed via the coverage arm
- **AND** an episode that matches only one of the topic tokens but ranks within the top `transcript_prefilter_cap` by `ts_rank` SHALL still be contributed via the `ts_rank` arm

<!-- @trace
source: topic-prefilter-forward-query-tokens
updated: 2026-06-07
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - skills-lock.json
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/answer_model_bakeoff.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/b23_prod_smoke.sh
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
-->

---
### Requirement: Cross-episode topical questions are deterministically routed to topic-prefilter search

The system SHALL apply a deterministic first-turn routing nudge so that cross-episode topical / narrative questions use `search_with_topic_prefilter` (candidate-scoping + voyage rerank) instead of relying on the LLM's free `tool_choice`, which empirically selects the un-scoped `search_across_episodes`. When the current user turn is detected as a cross-episode topical question, the system SHALL force the first agentic LLM call's `tool_choice` to `search_with_topic_prefilter`; once that tool returns, subsequent rounds SHALL revert to `tool_choice="auto"`. The nudge SHALL be controlled by a default-on boolean setting `enable_topic_routing_nudge`; when the setting is `False`, tool selection SHALL be bit-equivalent to the prior `tool_choice="auto"` behavior on every round.

The detector SHALL favor precision over recall: it SHALL classify a turn as cross-episode topical only when the question is NOT scoped to a specific episode reference (no `EPnnn` / `第n集` / 「這集」/「上一集」 style reference) AND the question yields at least two discriminating topic tokens (using the existing jieba topic-term extraction with stop-word and show-name removal). Turns that do not meet both conditions SHALL NOT be force-routed and SHALL keep `tool_choice="auto"`.

#### Scenario: Cross-episode topical question forces topic-prefilter on the first call

- **WHEN** a user asks a cross-episode topical question with ≥2 discriminating topic tokens and no specific episode reference
- **AND** `enable_topic_routing_nudge` is `True`
- **THEN** the first agentic LLM call SHALL be issued with `tool_choice` forcing `search_with_topic_prefilter`
- **AND** rounds after that tool returns SHALL use `tool_choice="auto"`

#### Scenario: Episode-scoped question is not force-routed

- **WHEN** a user question references a specific episode (e.g. contains `EP107` or 「這集」)
- **THEN** the routing nudge SHALL NOT fire
- **AND** the first agentic LLM call SHALL use `tool_choice="auto"`

#### Scenario: Question with fewer than two discriminating tokens is not force-routed

- **WHEN** a user question reduces to fewer than two discriminating topic tokens after filtering
- **THEN** the routing nudge SHALL NOT fire
- **AND** tool selection SHALL match the prior `tool_choice="auto"` behavior

#### Scenario: Flag off preserves prior behavior

- **WHEN** `enable_topic_routing_nudge` is `False`
- **THEN** every agentic LLM call SHALL use `tool_choice="auto"` regardless of the detector outcome

<!-- @trace
source: b22-cross-episode-topic-routing
updated: 2026-06-07
code:
  - backend/app/services/episode_finders.py
  - backend/app/services/chat_agent/tools.py
  - backend/app/services/chat_agent/agent.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - docs/roadmap.md
  - backend/eval/judge_config.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/b23_prod_smoke.sh
  - backend/app/core/config.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/answer_model_bakeoff.py
  - backend/app/services/chat_agent/routing.py
  - backend/scripts/b22_routing_probe.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - skills-lock.json
tests:
  - backend/tests/test_chat_agent_topic_routing_nudge.py
  - backend/tests/test_chat_agent_topic_prefilter_rerank.py
  - backend/tests/test_episode_finders_transcript_aware.py
-->