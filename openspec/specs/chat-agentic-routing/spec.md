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

Before the `ENABLE_AGENTIC_CHAT` default is flipped to `true` (which is out of scope of this change but in scope of a follow-up cleanup change), an evaluation run against `backend/eval/datasets/this-not-that-cool.json` SHALL be performed in staging with both pipelines (rule-based and agentic). The agentic pipeline SHALL meet all of the following gates relative to the rule-based baseline:

- `Recall@5` MUST NOT drop by more than 5 percentage points.
- `Faithfulness` MUST NOT drop by more than 0.05 (absolute, on a 0-1 scale).
- `answer_match` MUST NOT drop by more than 5 percentage points.

Evaluation results SHALL be captured in a case study at `docs/case-studies/agentic-chat-eval-<YYYY-MM>.md`. The gate decision MUST be recorded before the default flip lands.

#### Scenario: Recall regression blocks default flip

- **GIVEN** the staging eval shows agentic `Recall@5` is more than 5pp below the rule-based baseline
- **WHEN** anyone proposes flipping `ENABLE_AGENTIC_CHAT` default to `true`
- **THEN** the change SHALL be blocked until the regression is addressed or the gate is explicitly waived with stakeholder sign-off recorded in the case study

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