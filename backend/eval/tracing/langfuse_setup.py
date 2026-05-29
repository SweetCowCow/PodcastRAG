"""Langfuse Cloud SDK + dual-sink helpers for chat agent observability.

Part of change `eval-framework-upgrade` (2026-05-29). See design Decision 1 / 1a.

Refactored 2026-05-29 per Langfuse v3 best practice (langfuse/skills review):
- Removed custom `observe` wrapper — direct re-export from SDK
- `trace_span()` uses `langfuse.start_as_current_observation()` so Cloud
  also records the nested observation (was Cloud-orphan + PG-only before)
- PG sink reuses the OTel trace_id (16 bytes → UUID) so Cloud and PG join
  at trace level; span_id stays self-generated UUID (OTel span_id is 8 bytes,
  not UUID-compatible)
- `EVAL_TRACING_ENABLED` master kill-switch: when false, all observe/span
  helpers are no-ops. When true, SDK auto-inits from env on first
  `get_client()` call (no pre-init needed)
"""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from typing import Any, TypeVar
from uuid import UUID, uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

# Read once at import time per design Decision 1 of langfuse-sdk-overhead-rca
# (avoid per-call settings attribute lookup). Module reload required to toggle.
_TIMING_PROBE_ENABLED: bool = settings.eval_tracing_timing_probe

# Force this module's logger to INFO when probe enabled, otherwise default
# (root WARNING) swallows our `langfuse_timing:` measurement lines. Uvicorn
# captures stdout at INFO level for its own access log, so once we set the
# logger level, our lines reach Zeabur runtime log capture too.
if _TIMING_PROBE_ENABLED:
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        logger.addHandler(_h)
        logger.propagate = False


def _timed_call(span_name: str, op: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, float]:
    """Run `fn(*args, **kwargs)` and return (result, elapsed_ms).

    When `_TIMING_PROBE_ENABLED` is False, this still calls `fn` but skips
    `perf_counter` and log emission — net cost is one extra function call
    frame, sub-microsecond. When True, emits a `langfuse_timing:` logger
    line per call so prod runtime log can be grep+aggregated post-hoc.
    """
    if not _TIMING_PROBE_ENABLED:
        return fn(*args, **kwargs), 0.0
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(
        "langfuse_timing: span_name=%s op=%s elapsed_ms=%.3f",
        span_name, op, elapsed_ms,
    )
    return result, elapsed_ms

_F = TypeVar("_F", bound=Callable[..., Any])


# ─────────────────────────────────────────────────────────────────
# Eval context — bound by eval runner before each turn invocation.
# Prod user traffic leaves this None → PG sink skips (Cloud sink runs
# if EVAL_TRACING_ENABLED=true regardless).
# ─────────────────────────────────────────────────────────────────

_eval_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "eval_context", default=None
)


def set_eval_context(
    *, run_id: str, item_id: str, turn_idx: int
) -> None:
    """Bind eval-run identifiers to the current async context."""
    _eval_context.set(
        {"run_id": run_id, "item_id": item_id, "turn_idx": turn_idx}
    )


def reset_eval_context() -> None:
    _eval_context.set(None)


def get_eval_context() -> dict[str, Any] | None:
    return _eval_context.get()


# ─────────────────────────────────────────────────────────────────
# observe + propagate_attributes — direct SDK re-export with cheap
# no-op fallback when disabled OR SDK not installed.
# ─────────────────────────────────────────────────────────────────


def _noop_decorator(func: _F) -> _F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


@asynccontextmanager
async def _noop_async_cm() -> AsyncGenerator[None, None]:
    yield None


def observe(*args: Any, **kwargs: Any) -> Any:
    """Re-export of langfuse `@observe`. No-op when disabled / SDK missing.

    Usage:
        @observe(name="chat_agent_turn", as_type="agent")
        async def run_agent(...):
            ...
    """
    if not settings.eval_tracing_enabled:
        return _noop_decorator
    try:
        from langfuse import observe as _real_observe
    except ImportError:
        logger.warning("langfuse package not installed; @observe is no-op")
        return _noop_decorator
    return _real_observe(*args, **kwargs)


def propagate_attributes(**kwargs: Any) -> Any:
    """Re-export of langfuse `propagate_attributes` (v3+). No-op when disabled.

    Usage (must be inside an @observe-decorated function or active span):
        with propagate_attributes(session_id=..., metadata={...}, tags=[...]):
            ...
    """
    if not settings.eval_tracing_enabled:
        from contextlib import contextmanager

        @contextmanager
        def _noop():
            yield
        return _noop()
    try:
        from langfuse import propagate_attributes as _real
    except ImportError:
        from contextlib import contextmanager

        @contextmanager
        def _noop():
            yield
        return _noop()
    return _real(**kwargs)


def update_current_span(**kwargs: Any) -> None:
    """Re-export of langfuse.update_current_span. No-op when disabled.

    Use to set explicit input/output on the active observation, e.g.:
        update_current_span(input={"question": question})
    """
    if not settings.eval_tracing_enabled:
        return
    try:
        from langfuse import get_client
        get_client().update_current_span(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("update_current_span no-op: %s", exc)


def update_current_generation(**kwargs: Any) -> None:
    """Re-export of langfuse.update_current_generation. No-op when disabled."""
    if not settings.eval_tracing_enabled:
        return
    try:
        from langfuse import get_client
        get_client().update_current_generation(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("update_current_generation no-op: %s", exc)


# ─────────────────────────────────────────────────────────────────
# trace_span — dual-sink context manager:
#   * Cloud: opens a nested observation via start_as_current_observation
#   * PG: writes a row to eval_traces with trace_id aligned to OTel
# ─────────────────────────────────────────────────────────────────


def _otel_trace_id_to_uuid(otel_hex: str | None) -> UUID | None:
    """Convert 32-char OTel hex trace_id to a UUID. None → None."""
    if not otel_hex:
        return None
    try:
        return UUID(otel_hex)
    except (ValueError, TypeError):
        return None


@asynccontextmanager
async def trace_span(
    span_type: str,
    span_name: str,
    *,
    stage_name: str | None = None,
    as_type: str = "span",
) -> AsyncGenerator[dict[str, Any], None]:
    """Open a nested Langfuse observation + record matching PG row.

    `span_type` is the PG `eval_traces.span_type` discriminator
    (`'llm_call'|'tool_call'|'stage'`). `as_type` is the Langfuse
    observation type (`'span'|'generation'|'tool'|'agent'|...`).

    The yielded dict is the caller's per-span payload. Caller mutates
    in place; on exit we serialize relevant fields to the Cloud
    observation (input/output/model/usage) AND write a PG row when
    `eval_context` is bound.

    Cloud path runs whenever EVAL_TRACING_ENABLED=true (gates SDK init).
    PG path additionally requires eval_context to be set by the eval
    runner — prod user traffic bypasses PG sink.
    """
    if not settings.eval_tracing_enabled:
        yield {}
        return

    try:
        from langfuse import get_client
    except ImportError:
        yield {}
        return

    langfuse = get_client()
    record: dict[str, Any] = {}
    started_at = datetime.now(UTC)

    # Per-op timing accumulators for langfuse-sdk-overhead-rca measurement.
    # Always set even when probe disabled — zero-cost when _TIMING_PROBE_ENABLED=False
    # because _timed_call short-circuits and we skip the summary log.
    t_enter_ms = 0.0
    t_exit_ms = 0.0
    t_update_ms = 0.0
    t_get_trace_id_ms = 0.0

    # Open Cloud observation. Always — even if eval_context is None,
    # Cloud trace tree still benefits from nested span hierarchy.
    # Manual timing of `with` enter/exit because context manager isn't a
    # plain function call; _timed_call only fires logger when probe enabled.
    if _TIMING_PROBE_ENABLED:
        _t0 = time.perf_counter()
    obs_cm = langfuse.start_as_current_observation(
        as_type=as_type, name=span_name
    )
    obs = obs_cm.__enter__()
    if _TIMING_PROBE_ENABLED:
        t_enter_ms = (time.perf_counter() - _t0) * 1000.0
        logger.info(
            "langfuse_timing: span_name=%s op=enter elapsed_ms=%.3f",
            span_name, t_enter_ms,
        )

    try:
        try:
            yield record
        finally:
            # Push caller-supplied fields onto the Cloud observation.
            cloud_payload: dict[str, Any] = {}
            for k in ("input", "output", "metadata", "model", "usage_details"):
                if k in record:
                    cloud_payload[k] = record[k]
            if cloud_payload:
                try:
                    _, t_update_ms = _timed_call(
                        span_name, "update", obs.update, **cloud_payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("obs.update failed: %s", exc)

            # Capture OTel IDs for PG join key alignment.
            try:
                otel_trace_id, t_get_trace_id_ms = _timed_call(
                    span_name, "get_trace_id", langfuse.get_current_trace_id,
                )
            except Exception:  # noqa: BLE001
                otel_trace_id = None
    finally:
        if _TIMING_PROBE_ENABLED:
            _t0 = time.perf_counter()
        obs_cm.__exit__(None, None, None)
        if _TIMING_PROBE_ENABLED:
            t_exit_ms = (time.perf_counter() - _t0) * 1000.0
            logger.info(
                "langfuse_timing: span_name=%s op=exit elapsed_ms=%.3f",
                span_name, t_exit_ms,
            )
            # Per-span summary line — caller can correlate via Uvicorn access log.
            logger.info(
                "langfuse_timing_summary: span_name=%s total_ms=%.3f "
                "enter=%.3f exit=%.3f update=%.3f get_trace_id=%.3f",
                span_name,
                t_enter_ms + t_exit_ms + t_update_ms + t_get_trace_id_ms,
                t_enter_ms, t_exit_ms, t_update_ms, t_get_trace_id_ms,
            )

    # PG sink — only when eval runner has bound a run.
    ctx = get_eval_context()
    if ctx is None:
        return

    ended_at = datetime.now(UTC)
    elapsed_ms = int((ended_at - started_at).total_seconds() * 1000)

    trace_uuid = _otel_trace_id_to_uuid(otel_trace_id) or uuid4()
    pg_row: dict[str, Any] = {
        "span_id": uuid4(),
        "trace_id": trace_uuid,
        "parent_span_id": ctx.get("current_parent_span_id"),
        "run_id": ctx["run_id"],
        "item_id": ctx["item_id"],
        "turn_idx": ctx["turn_idx"],
        "span_type": span_type,
        "span_name": span_name,
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_ms": elapsed_ms,
        "stage_name": stage_name,
    }
    # Lift LLM / tool-specific fields from record into the PG row.
    for k in (
        "llm_model", "llm_finish_reason", "llm_prompt_tokens",
        "llm_completion_tokens", "llm_messages_json", "llm_output_text",
        "tool_name", "tool_args_json", "tool_result_chunks_json",
        "search_query",
    ):
        if k in record:
            pg_row[k] = record[k]

    # Lazy import — avoids circular dep at module load.
    from eval.tracing.span_writer import write_span
    try:
        await write_span(pg_row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("trace_span PG sink failed: %s", exc)
