## Summary

Investigation-only spike change to identify the actual source of Langfuse Cloud SDK latency overhead measured at P95 +3375ms in `eval-framework-upgrade` Phase 4.4 prod 灰度. Outcome is a decision document, not a code fix.

## Motivation

Phase 4.4 of `eval-framework-upgrade` (archived 2026-05-30) measured P95 ON-OFF delta of +3375ms when `EVAL_TRACING_ENABLED=true` on prod backend. The original case study concluded the cause was Langfuse Cloud SDK HTTP roundtrip and opened `langfuse-self-host-evaluation` as the follow-up.

A subsequent investigation (during `/spectra-apply span-writer-batch-queue` on 2026-05-30) attempted to attribute the overhead to synchronous PG dual-sink writes. That hypothesis was falsified by grep: `set_eval_context()` is never called anywhere in the codebase, so `_eval_context` is always `None`, and `trace_span` early-returns at line 232 before any PG `write_span` call. PG dual-sink has never actually fired in prod or eval runs.

We now know the overhead is **entirely on the Langfuse Cloud SDK side** (v3 Python SDK, OpenTelemetry-based), but the specific code path responsible is unknown. Suspects include:
- `with langfuse.start_as_current_observation(...)` context manager enter/exit
- `obs.update(input=..., output=..., metadata=...)` payload serialization or sync flush trigger
- `langfuse.get_current_trace_id()` blocking I/O
- OTEL span setup / propagation overhead

Langfuse Cloud SDK officially documents ~0.1ms overhead via async + batching, but our usage pattern (v3 OTEL adapter + sync context manager + large payload updates) may not match the assumptions in that benchmark. Without per-call timing, any "fix" risks solving the wrong problem (the `span-writer-batch-queue` rejected proposal is exhibit A).

This change is a controlled spike: instrument the suspect calls with timing wrappers, re-run a reduced 4.4-style latency probe (30 calls/phase to keep cost low), and identify the actual bottleneck before designing or proposing a structural fix.

## Proposed Solution

Phase 1: Instrumentation
1. Add per-call timing wrappers around four suspect operations inside `backend/eval/tracing/langfuse_setup.py::trace_span`:
   - `with langfuse.start_as_current_observation(...)` enter time
   - `with` block exit time (covers Langfuse internal teardown)
   - `obs.update(...)` call time
   - `langfuse.get_current_trace_id()` call time
2. Emit timings via existing `logger.info` (operator-readable, no new metrics infra)
3. Add an aggregation logger that emits per-request totals (e.g., "request X: N spans, total Langfuse overhead Y ms, breakdown {enter:..., exit:..., update:..., trace_id:...}")
4. Gate the instrumentation behind a separate env flag `EVAL_TRACING_TIMING_PROBE=true` so it can be toggled independently of `EVAL_TRACING_ENABLED`

Phase 2: Measurement
1. Toggle `EVAL_TRACING_ENABLED=true` + `EVAL_TRACING_TIMING_PROBE=true` × 4 prod service + redeploy backend
2. Re-run 4.4-style latency probe (30 call/phase × 2 phase, 4 query mix b06/b11/b18/b20, unique suffix cache miss)
3. Collect per-call timings from prod logs (download via `npx zeabur deployment log --type runtime`, redact per `feedback_zeabur_deployment_log_leaks_query_string.md`)
4. Aggregate breakdown: which of the four suspect operations is the dominant contributor to +3-6s on retrieval-heavy queries?

Phase 3: Decision
1. Based on timing breakdown, write case study identifying the actual bottleneck
2. Pick one of three forward paths:
   - **3a**. Bottleneck is `obs.update` payload size — propose `langfuse-payload-trim` (lazy fix: truncate input/output/metadata to small caps before `obs.update`)
   - **3b**. Bottleneck is `start_as_current_observation` / OTEL setup — propose `langfuse-instrumentation-pattern-change` (e.g., switch from context manager to manual span API)
   - **3c**. Bottleneck is HTTP flush / network roundtrip — promote `langfuse-self-host-evaluation` back to optional and propose with measured numbers
3. Toggle `EVAL_TRACING_TIMING_PROBE=false` + `EVAL_TRACING_ENABLED=false` × 4 service + redeploy backend; return prod to default state

## Non-Goals

- Implementing the actual fix (separate change after RCA outcome)
- Self-hosting Langfuse (this change is RCA only; self-host may or may not be the recommended path)
- Removing the Cloud SDK or switching observability stacks
- Changing the PG dual-sink design or wiring `set_eval_context()` (separate `eval-runner-eval-context-plumbing` follow-up)
- Adding new metrics endpoints, dashboards, or observability infrastructure beyond `logger.info` lines

## Alternatives Considered

**Skip RCA, directly propose self-host**: Rejected. We'd be guessing again. The `span-writer-batch-queue` mistake shows the cost of skipping verification — a complete propose with design + spec + tasks was based on a wrong hypothesis.

**Use Langfuse Cloud's UI to debug**: Rejected. Cloud UI shows trace data but not SDK-side timing breakdown of where time is spent in the caller process.

**Add APM tool (Sentry / DataDog / OpenTelemetry trace)**: Rejected. Over-engineered for a single targeted RCA spike. `logger.info` lines suffice; we don't need a new observability stack to diagnose the existing one.

## Impact

- Affected specs: `eval-observability` (modified — add timing-probe env flag scenario; instrumentation timing wrapper is part of debugging tooling)
- Affected code:
  - Modified: `backend/eval/tracing/langfuse_setup.py` (add timing wrappers around the four suspect ops, gated by `EVAL_TRACING_TIMING_PROBE` env)
  - Modified: `backend/app/core/config.py` Settings (add `EVAL_TRACING_TIMING_PROBE: bool = False` field with `extra="ignore"` discipline per `feedback_pydantic_settings_extra_forbid_leaks.md`)
  - New: none
  - Removed: none
- Affected docs (not in commit per convention):
  - New: `docs/case-studies/langfuse-sdk-overhead-rca-2026-05-XX.md` (Phase 3 outcome)
- Affected env / runtime:
  - New env var `EVAL_TRACING_TIMING_PROBE` (default false) on 4 prod service; toggled true briefly during Phase 2 measurement and returned to false at end of change
  - Same `EVAL_TRACING_ENABLED=true / false` toggle pattern as 4.4 (one redeploy in, one redeploy out)
- Cost: Phase 2 measurement burns ~140 prod /query calls (same protocol as 4.4); estimated $20-50 LLM cost
- Risk: Phase 2 measurement temporarily exposes prod chat agent to instrumented code path; timing wrappers add their own (small) overhead, but the goal is RELATIVE attribution between four operations, not absolute target latency — wrapper overhead is constant across all four
