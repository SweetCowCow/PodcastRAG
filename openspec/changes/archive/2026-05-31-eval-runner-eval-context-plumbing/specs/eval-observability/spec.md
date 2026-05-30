## ADDED Requirements

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
