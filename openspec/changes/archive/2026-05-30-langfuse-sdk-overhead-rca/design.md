# Design — langfuse-sdk-overhead-rca

## Context

`eval-framework-upgrade` Phase 4.4 measured P95 +3375ms with `EVAL_TRACING_ENABLED=true`. The initial case study attributed the regression to Langfuse Cloud SDK HTTP roundtrip; a follow-up investigation revealed the attempted alternative explanation (synchronous PG dual-sink writes) is also wrong because `set_eval_context()` is never called in the codebase, making the PG path dead code under all current invocations.

The remaining hypothesis space is entirely Langfuse Cloud SDK v3 (OpenTelemetry-based, Python). The SDK officially documents ~0.1ms overhead via async batching, but our usage pattern in `backend/eval/tracing/langfuse_setup.py::trace_span` involves four operations that occur synchronously in the request path:

1. `with langfuse.start_as_current_observation(as_type=..., name=...) as obs:` — context manager enter
2. `with` block teardown — context manager exit
3. `obs.update(input=..., output=..., metadata=..., model=..., usage_details=...)` — payload push
4. `langfuse.get_current_trace_id()` — OTEL trace ID retrieval

Each is invoked once per emitted span. For a retrieval-heavy `/query` request emitting 10-30 spans, even a 100ms per-call cost on one of these four would compound to 1-3 seconds of blocking — matching observed +3-6s on b18/b20.

Without per-operation timing, picking a fix is a guess. The `span-writer-batch-queue` rejected proposal cost us a full propose + design + spec + tasks artifact set before grep falsified its premise. Spike-then-fix is the correct order.

## Goals / Non-Goals

### Goals

1. Identify which of the four suspect operations dominates `+3375ms` P95 overhead
2. Produce a case study with breakdown table + per-query metrics
3. Choose a forward path (3a payload trim / 3b instrumentation pattern / 3c self-host) backed by measured numbers

### Non-Goals

- Fix the latency (separate change based on RCA outcome)
- Add general observability infrastructure (no APM, no metrics endpoints)
- Re-architect dual-sink or wire `set_eval_context()` (separate `eval-runner-eval-context-plumbing` follow-up)
- Trim payload size as a workaround without measuring whether payload is the actual contributor

## Decisions

### Decision 1: Instrument with `time.perf_counter()` + `logger.info`, not OpenTelemetry meta-spans

**Choice**: Wrap each of the four suspect operations with `t0 = time.perf_counter()` ... `elapsed = time.perf_counter() - t0`, emit via `logger.info("langfuse_timing: ...")` lines.

**Why**:
- Bottoms-up simplicity — no new dependency, no meta-tracing of the tracing system (which would itself add overhead and confuse the measurement)
- Logger lines are easy to grep + aggregate post-run with Python script
- Doesn't pollute the Cloud trace tree we're trying to measure

**Alternative considered (rejected)**: Add an OpenTelemetry meta-span around each suspect operation. Rejected because meta-spans would emit through the same Langfuse SDK we're measuring, contaminating results.

**Alternative considered (rejected)**: Use `py-spy` / `cProfile` for sampling profiling. Rejected because they require attaching to a running process (Zeabur prod doesn't expose a sidecar shell easily) and would catch unrelated app code paths.

### Decision 2: Gate timing probe behind separate env `EVAL_TRACING_TIMING_PROBE`

**Choice**: New env flag `EVAL_TRACING_TIMING_PROBE` (default false). Timing wrappers fire only when this flag is true AND `EVAL_TRACING_ENABLED=true`. Operators can leave tracing on without paying the (small) timing-wrapper cost in normal operation.

**Why**:
- Allows independent toggle: ship the wrappers to prod permanently, only fire them during measurement windows
- Avoids permanently coupling RCA infrastructure to tracing
- Future RCA spikes can reuse the flag pattern

**Alternative considered (rejected)**: Reuse `EVAL_TRACING_ENABLED` to also gate timing. Rejected because measurement windows are short (~30 min) and we want operators to be able to run normal tracing without measurement overhead.

### Decision 3: 30 call/phase × 2 phase measurement protocol

**Choice**: Reuse 4.4's `/tmp/latency_probe.py` script but reduce REPS_PER_QUERY from 18 to 7 (4 query × 7 reps = 28 calls + 5 warmup = 33 per phase; rounded up to 30 for clarity in case study).

**Why**:
- 4.4 used 72/phase = 144 total; estimated $40-80 LLM cost. RCA can be done at a third of that.
- Statistical power: 28 samples per phase still gives meaningful P95 estimate (within ±100ms 70% CI) — sufficient to attribute order-of-magnitude differences between the four suspect operations
- Smaller sample = faster turnaround (~10 min wall vs 35 min)

**Alternative considered (rejected)**: Single representative query × 50 reps. Rejected because mixed query workload (b06/b11 light + b18/b20 heavy) reveals per-operation cost behavior under different span tree depths — single query loses that signal.

### Decision 4: Outcome is a case study + a forward proposal, not a code fix

**Choice**: This change ends with the operator (Claude + user) reading the timing breakdown, deciding among 3a/3b/3c, and opening a follow-up Spectra change with the chosen fix.

**Why**:
- Investigation-only changes have precedent in this repo (memory references `agent-trace-telemetry archive` as "Investigation-only：把 telemetry 工具架好不修問題")
- Keeps the RCA cycle short; fix design depends on bottleneck identity
- Avoids the `span-writer-batch-queue` mistake of designing a fix before knowing what to fix

**Alternative considered (rejected)**: Inline both RCA and fix in one change. Rejected because the fix design varies dramatically by bottleneck identity (payload trim is trivial; instrumentation pattern change touches every call site; self-host is multi-week infra work).

## Implementation Contract

### 1. Timing wrapper structure

A new helper function `_timed_call(name, fn, *args, **kwargs)` SHALL wrap synchronous calls and emit a logger line in the form `langfuse_timing: span_name=X op=Y elapsed_ms=N`. The four suspect operations SHALL be wrapped by name `enter`, `exit`, `update`, `get_trace_id`. Wrapper SHALL be a no-op when `EVAL_TRACING_TIMING_PROBE` is false (no logger emission, no `perf_counter` call).

Verification: existing `trace_span` callers SHALL observe no behavior change when the flag is false; a grep for `langfuse_timing:` in prod logs SHALL return zero lines when the flag is false.

### 2. Per-request aggregation

At the end of each `trace_span` invocation (after the four operations complete), the wrapper SHALL emit one summary line `langfuse_timing_summary: span_name=X total_ms=N enter=A exit=B update=C get_trace_id=D` with the per-op contributions. When `EVAL_TRACING_TIMING_PROBE` is false, no summary line SHALL be emitted.

Verification: prod logs during Phase 2 measurement SHALL contain N×span_count summary lines, one per span emitted, that can be grouped by request id (via correlation through existing access log).

### 3. Env flag plumbing

`backend/app/core/config.py` Settings SHALL gain `EVAL_TRACING_TIMING_PROBE: bool = False` with `extra="ignore"` already in place per `feedback_pydantic_settings_extra_forbid_leaks.md`. The flag SHALL be read at module import time of `langfuse_setup.py` (no per-call env read for performance).

Verification: unit test in `backend/tests/eval/tracing/test_timing_probe.py` SHALL assert that `_timed_call` skips the timing logic when the flag is False and emits a log line when True.

### 4. Measurement script and aggregation

The Phase 2 measurement SHALL reuse `/tmp/latency_probe.py` with `REPS_PER_QUERY=7`. After ON phase, an aggregation script (delivered inline in tasks 2.4) SHALL parse prod runtime logs and emit a markdown table containing:
- per query (b06/b11/b18/b20): total span count, mean per-op elapsed_ms breakdown
- aggregate: P50/P95 per-op contribution as % of overall request overhead
- top-3 largest individual span overheads (debug for outliers)

Verification: aggregation output SHALL show one or more operations contributing > 30% of total overhead; case study SHALL identify the dominant op by name.

### 5. Decision artifact

Phase 3 case study SHALL contain:
- Title and date
- Background linking to `eval-framework-upgrade` 4.4 + the parked `span-writer-batch-queue`
- Phase 1-2 results with breakdown table
- Identified bottleneck and chosen forward path (one of 3a/3b/3c)
- Follow-up change name proposed (e.g., `langfuse-payload-trim`, `langfuse-instrumentation-pattern-change`, `langfuse-self-host-evaluation`)

Verification: case study path is `docs/case-studies/langfuse-sdk-overhead-rca-2026-05-XX.md` and contains all five sections.

### 6. Scope boundaries

- **In scope**: `langfuse_setup.py` instrumentation, `Settings` field add, Phase 2 measurement, case study Phase 3
- **Out of scope**: implementing any of 3a/3b/3c, `set_eval_context()` wiring, span queue refactor, OpenTelemetry config changes, payload size limits (those are fix candidates, not this change)

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Timing wrappers themselves add measurable overhead, contaminating measurement | Wrappers use stdlib `perf_counter`; per-call overhead is sub-microsecond. Wrappers are off-by-default; on only during the 10-min measurement window. |
| Phase 2 measurement adds prod traffic temporarily (~$20-50 cost) | Same magnitude as 4.4. Within budget per `feedback_cost_awareness.md` pilot threshold. |
| logger.info lines flood Zeabur log retention | Phase 2 runs are short; logs are read once and decision is made. No long-running measurement. |
| Prod chat users observe Phase 2 latency overhead during measurement | Same as 4.4 — toggle on, measure 10 min, toggle off. Low traffic at measurement window. |
| Aggregation script can't correlate logs to specific requests | Use existing Uvicorn access log + add a request-id field to summary line via FastAPI's request context |
| Decision lock-in: case study picks 3c (self-host) but later a 3a payload-trim would also have worked | Case study SHALL include all three breakdowns; future re-evaluation possible if 3c proves costly |

## Migration Plan

### Deploy

1. Implement Phase 1 code (timing wrappers + Settings field + unit tests)
2. `gitleaks` + `pytest backend/tests/eval/tracing/test_timing_probe.py`
3. Commit + push main → Zeabur auto-deploy backend
4. Phase 2 toggle: `EVAL_TRACING_ENABLED=true` + `EVAL_TRACING_TIMING_PROBE=true` × 4 service + redeploy backend, wait RUNNING
5. Run `/tmp/latency_probe.py` OFF and ON phase per Decision 3 (~10 min wall each)
6. Download prod runtime log via `npx zeabur deployment log --type runtime` (redact `?token=` / `?key=` per `feedback_zeabur_deployment_log_leaks_query_string.md` before saving)
7. Run aggregation script, produce breakdown table
8. Phase 3 case study + forward decision

### Rollback / Cleanup

- Phase 2 cleanup is mandatory: `EVAL_TRACING_ENABLED=false` + `EVAL_TRACING_TIMING_PROBE=false` × 4 service + redeploy backend
- Timing wrapper code stays in tree (default-off flag pattern; reusable for future RCA)
- No DB schema change; no data migration

## Open Questions

- **Q1**: If the bottleneck is OTEL setup (which happens once per process for global tracer init, not per span), can our per-span timing capture it? **Resolution: include a separate "first-span vs subsequent-span" comparison in the aggregation table to detect this**. If first span is dramatically slower than subsequent ones, the bottleneck is global setup, not per-span operations.
- **Q2**: Should we also instrument the `@observe` decorator wrapper at agent.py line 294? **Resolution: yes if Phase 2 results are inconclusive on per-span attribution** — out of scope for first measurement run, added as a stretch task if needed.
