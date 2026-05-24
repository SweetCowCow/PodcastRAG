## ADDED Requirements

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
