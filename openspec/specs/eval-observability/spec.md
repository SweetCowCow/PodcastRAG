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