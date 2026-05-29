# Spec Delta — eval-observability (langfuse-sdk-overhead-rca)

## ADDED Requirements

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

