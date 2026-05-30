# eval-observability Specification

## Purpose

TBD - created by archiving change 'eval-framework-upgrade'. Update Purpose after archive.

## Requirements

### Requirement: Eval observability stack SHALL use Langfuse Cloud (SaaS)

The system SHALL use Langfuse Cloud (`https://cloud.langfuse.com`, Free tier) as the trace UI backend. The backend services SHALL initialize the Langfuse Python SDK with `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST=https://cloud.langfuse.com` environment variables. Chat agent eval runs SHALL emit trace spans to Langfuse Cloud via the SDK. Operators SHALL be able to open the Langfuse Cloud Web UI and view a complete trace tree (LLM rounds nested under tool dispatches nested under turns) for any recent eval run. No self-hosted Langfuse infrastructure SHALL be deployed in scope of this change.

#### Scenario: operator views trace tree for a recent chat eval run

- **WHEN** an operator opens the Langfuse Cloud Web UI shortly after completing a chat eval baseline run
- **THEN** the UI SHALL display traces for that run, grouped by `(run_id, item_id, turn_idx)`
- **AND** each trace SHALL show a nested span tree with LLM round spans (containing input messages + output text) under their parent turn span, with tool call spans interleaved


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Cloud usage tracking SHALL define self-host re-evaluation triggers

The operator SHALL monitor the Langfuse Cloud monthly units consumption (via `cloud.langfuse.com → Settings → Usage`) at least once per week. The system SHALL define explicit thresholds at which self-hosted Langfuse deployment is re-evaluated: monthly units exceeding 40,000 (80% of Free tier 50,000 quota), monthly units exceeding 100,000 (saturating Core $29 tier), trace content beginning to include personally identifiable information (PII) or private user conversations, or Langfuse Cloud pricing or quota changes.

#### Scenario: monthly units cross 40k threshold

- **WHEN** the Langfuse Cloud dashboard reports monthly units > 40,000 in a given calendar month
- **THEN** the operator SHALL open a discussion to compare upgrading to Langfuse Core ($29/month) against re-evaluating self-hosted deployment
- **AND** the operator SHALL record the decision and rationale in the project memory

#### Scenario: trace content begins to include PII

- **WHEN** trace payloads begin to contain user-identifiable information or private user conversations (e.g., after full-site authentication launch)
- **THEN** the operator SHALL halt new Cloud upload (toggle `EVAL_TRACING_ENABLED=false` on prod services) until self-hosted Langfuse is in place
- **AND** the existing PG `eval_traces` table SHALL remain authoritative for historical RCA queries during the transition


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: `eval_traces` PostgreSQL table SHALL store span tree data

A new `eval_traces` table SHALL exist in the prod PostgreSQL database with columns covering OTel-style span fields: `span_id UUID PK`, `trace_id UUID`, `parent_span_id UUID NULL`, `run_id TEXT`, `item_id TEXT`, `turn_idx INT`, `span_type TEXT` (`llm_call|tool_call|stage`), `span_name TEXT`, `started_at TIMESTAMPTZ`, `ended_at TIMESTAMPTZ NULL`, `elapsed_ms INT NULL`, LLM-specific fields (`llm_model`, `llm_finish_reason`, `llm_prompt_tokens`, `llm_completion_tokens`, `llm_messages_json JSONB`, `llm_output_text TEXT`), tool-specific fields (`tool_name`, `tool_args_json JSONB`, `tool_result_chunks_json JSONB`, `search_query TEXT`), and `stage_name TEXT`. Indexes SHALL exist on `(run_id, item_id)`, `(trace_id)`, and `(search_query) WHERE search_query IS NOT NULL`.

#### Scenario: SQL audit retrieves all spans for an item

- **WHEN** an operator runs `SELECT * FROM eval_traces WHERE run_id = '<X>' AND item_id = 'b18' ORDER BY started_at`
- **THEN** the result SHALL include all spans for that item including LLM messages and tool result chunks
- **AND** the result SHALL be retrievable via the existing `mcp__podcastrag-pg__query` MCP tool


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Span writer SHALL fail safely without aborting the host eval run

The `span_writer.write_span` function SHALL wrap PG insert and Langfuse SDK calls in try/except blocks. On failure, it SHALL log a warning and return; it SHALL NOT raise to the caller. The chat agent loop and eval runner SHALL invoke `write_span` as fire-and-forget; no production code path SHALL block on span persistence.

#### Scenario: PG insert failure does not abort chat agent loop

- **WHEN** an exception is raised inside the `eval_traces` insert path during a live chat agent query
- **THEN** the chat agent loop SHALL complete the request and return a normal response to the user
- **AND** a warning log entry SHALL record the span write failure


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Tracing decorator SHALL be env-gated for prod traffic

The `@observe` decorator on the chat agent loop SHALL be enabled or disabled per a runtime environment flag (e.g., `EVAL_TRACING_ENABLED`). The default SHALL be enabled only for eval runs (gated by the runner setting the env at process start). Prod user traffic SHALL NOT emit trace spans by default; operators MAY opt in for a bounded observation window by toggling the env on a prod deployment.

#### Scenario: prod user traffic does not emit spans by default

- **WHEN** `EVAL_TRACING_ENABLED` is unset or `false` and a real user submits a chat query in prod
- **THEN** no rows SHALL be written to `eval_traces` for that query
- **AND** Langfuse SHALL NOT receive trace spans for that query

#### Scenario: eval runner enables tracing for its own process

- **WHEN** the chat agent eval runner starts a run
- **THEN** the runner process SHALL set `EVAL_TRACING_ENABLED=true` in its own environment before any chat agent call
- **AND** every chat agent call within that process SHALL emit trace spans

<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Tracing pipeline SHALL support an optional per-call timing probe

The system SHALL support runtime measurement of internal Langfuse SDK operation timing without requiring the regular tracing path to incur measurement overhead. An environment flag `EVAL_TRACING_TIMING_PROBE` (default false) SHALL gate the timing-instrumentation code paths inside `backend/eval/tracing/langfuse_setup.py`. When the flag is true AND `EVAL_TRACING_ENABLED=true`, each call to `trace_span` SHALL emit per-operation `logger.info` lines covering the four suspect synchronous operations (`enter`, `exit`, `update`, `get_trace_id`) and one aggregate summary line per span. When the flag is false, no timing-instrumentation logger lines SHALL be emitted, and the wrappers SHALL be no-ops (no `time.perf_counter` invocations).

#### Scenario: timing probe disabled by default

- **WHEN** the backend service starts with `EVAL_TRACING_ENABLED=true` and `EVAL_TRACING_TIMING_PROBE` unset or `false`
- **THEN** the runtime log SHALL NOT contain any line matching `langfuse_timing:` or `langfuse_timing_summary:`
- **AND** chat agent request latency SHALL NOT be affected by timing instrumentation

#### Scenario: timing probe enabled emits per-operation timings

- **WHEN** the backend service starts with `EVAL_TRACING_ENABLED=true` and `EVAL_TRACING_TIMING_PROBE=true` and serves a `/query` request
- **THEN** the runtime log SHALL contain per-span lines of the form `langfuse_timing: span_name=<name> op=<enter|exit|update|get_trace_id> elapsed_ms=<n>`
- **AND** the runtime log SHALL contain a per-span summary line `langfuse_timing_summary: span_name=<name> total_ms=<n> enter=<a> exit=<b> update=<c> get_trace_id=<d>`

#### Scenario: timing probe is independently toggleable from tracing

- **WHEN** an operator toggles `EVAL_TRACING_TIMING_PROBE` from false to true and back to false via `npx zeabur variable update` + redeploy
- **THEN** the regular `EVAL_TRACING_ENABLED` flag SHALL remain at its previously configured value
- **AND** trace span emission to Langfuse Cloud SHALL continue uninterrupted during both transitions

<!-- @trace
source: langfuse-sdk-overhead-rca
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Backend SHALL bind eval context from admin-issued HTTP headers on the chat query endpoint

The backend `/shows/{show_id}/query` endpoint SHALL accept three optional HTTP headers: `X-Eval-Run-Id`, `X-Eval-Item-Id`, and `X-Eval-Turn-Idx`. The endpoint SHALL include a FastAPI dependency `bind_eval_context` that activates eval context binding when ALL of the following conditions hold: (1) the authenticated user has `role == "admin"`; (2) all three headers are present and non-empty; (3) `X-Eval-Turn-Idx` parses as a non-negative integer. When all conditions hold, the dependency SHALL invoke `set_eval_context(run_id=<header>, item_id=<header>, turn_idx=<int>)` before the endpoint handler executes the chat agent, and SHALL invoke `reset_eval_context()` in a `finally` block after the handler returns or raises. When any condition fails, the dependency SHALL leave the eval context ContextVar untouched (remaining at its prior value, normally `None`). The dependency SHALL NOT return any HTTP 4xx response on missing or malformed headers — failure modes SHALL be silent skip, not error.

#### Scenario: admin caller with complete headers binds eval context for the request lifetime

- **GIVEN** an authenticated admin session and a request to `POST /shows/{id}/query` carrying headers `X-Eval-Run-Id: eval-X`, `X-Eval-Item-Id: b20`, `X-Eval-Turn-Idx: 0`
- **WHEN** the request reaches the chat agent handler
- **THEN** `get_eval_context()` returns `{"run_id": "eval-X", "item_id": "b20", "turn_idx": 0}` for the duration of the handler
- **AND** after the handler returns, `get_eval_context()` returns `None` again

#### Scenario: non-admin caller with complete headers does NOT bind eval context

- **GIVEN** an authenticated non-admin (member) session and a request carrying all three `X-Eval-*` headers
- **WHEN** the request reaches the chat agent handler
- **THEN** the request completes with HTTP 200 (or the normal response code for the chat path)
- **AND** `get_eval_context()` returns `None` throughout the handler

#### Scenario: admin caller with missing headers does NOT bind eval context

- **GIVEN** an authenticated admin session and a request that omits `X-Eval-Item-Id`
- **WHEN** the request reaches the chat agent handler
- **THEN** the request completes normally without HTTP 4xx
- **AND** `get_eval_context()` returns `None` throughout the handler

#### Scenario: admin caller with malformed turn_idx header does NOT bind eval context

- **GIVEN** an authenticated admin session and a request carrying `X-Eval-Turn-Idx: not-a-number`
- **WHEN** the request reaches the chat agent handler
- **THEN** the request completes normally without HTTP 4xx
- **AND** `get_eval_context()` returns `None` throughout the handler


<!-- @trace
source: eval-runner-eval-context-plumbing
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: PG eval_traces SHALL contain populated run_id, item_id, and turn_idx for runner-driven requests

For any HTTP request to `/shows/{show_id}/query` that has successfully bound an eval context via `bind_eval_context` (admin role + three valid headers), every `eval_traces` row written during that request lifetime SHALL have `run_id`, `item_id`, and `turn_idx` populated with values matching the `set_eval_context()` call. This requirement applies to all three `span_type` values (`llm_call`, `tool_call`, `stage`).

#### Scenario: runner-driven turn writes spans with populated locator columns

- **GIVEN** the eval runner v2 invokes `/query` with admin session and headers `X-Eval-Run-Id: eval-Y`, `X-Eval-Item-Id: mt03`, `X-Eval-Turn-Idx: 1`
- **WHEN** the chat agent handler completes, emitting at least one `llm_call` span and at least one `tool_call` span
- **THEN** SQL `SELECT DISTINCT run_id, item_id, turn_idx FROM eval_traces WHERE run_id = 'eval-Y' AND item_id = 'mt03' AND turn_idx = 1` returns exactly one row `('eval-Y', 'mt03', 1)`
- **AND** every span written under that request lifetime has all three columns equal to those values

#### Scenario: prod user traffic with no eval context does NOT write to eval_traces

- **GIVEN** a non-admin user session and a normal `POST /shows/{id}/query` request with no `X-Eval-*` headers
- **WHEN** the chat agent handler completes
- **THEN** SQL `SELECT COUNT(*) FROM eval_traces WHERE created_at >= <request_start_time>` returns the same count as before the request
- **AND** the chat response is returned with HTTP 200 as in current behavior

<!-- @trace
source: eval-runner-eval-context-plumbing
updated: 2026-05-31
code:
  - skills-lock.json
-->