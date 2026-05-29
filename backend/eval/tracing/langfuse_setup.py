"""Langfuse Cloud (Free tier) SDK initialization for eval trace observability.

Part of change `eval-framework-upgrade` (2026-05-29). See design Decision 1.

Three modes (gated by `Settings.eval_tracing_enabled` and presence of keys):

1. **Disabled** (`EVAL_TRACING_ENABLED=false`, default for prod user traffic):
   `init_langfuse()` returns None, `observe` decorator is a no-op wrapper.
2. **Enabled, keys present**: returns a configured `Langfuse` client connected
   to `LANGFUSE_HOST` (default `https://cloud.langfuse.com`).
3. **Enabled, keys missing**: logs a warning and returns None — calling code
   SHALL treat None as "tracing unavailable, proceed without spans". This
   matches the eval-observability spec scenario "prod user traffic does not
   emit spans by default" and the design Decision 7 fail-safe rule.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from typing import Any, TypeVar
from uuid import UUID, uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

_client: Any = None
_initialized: bool = False


# Eval context — set by the eval runner before each turn invocation.
# Prod user traffic leaves this None, which means `trace_span` skips the PG
# sink (Cloud sink via @observe still runs if EVAL_TRACING_ENABLED=true,
# but real prod use case keeps EVAL_TRACING_ENABLED=false anyway).
_eval_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "eval_context", default=None
)


def set_eval_context(
    *, run_id: str, item_id: str, turn_idx: int, trace_id: UUID | None = None
) -> None:
    """Bind eval-run identifiers to the current async context.

    Called by the eval runner before each `run_agent` invocation. The
    trace_id (auto-generated if omitted) is reused across all spans of
    a single turn so the span tree can be reconstructed.
    """
    _eval_context.set(
        {
            "run_id": run_id,
            "item_id": item_id,
            "turn_idx": turn_idx,
            "trace_id": trace_id or uuid4(),
        }
    )


def reset_eval_context() -> None:
    """Clear the current eval context. Call after each turn completes."""
    _eval_context.set(None)


def get_eval_context() -> dict[str, Any] | None:
    """Return the current eval context, or None if not bound (prod traffic)."""
    return _eval_context.get()


def init_langfuse() -> Any | None:
    """Initialize and cache the Langfuse client. Idempotent.

    Returns the client on success, None when disabled or keys missing.
    """
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    if not settings.eval_tracing_enabled:
        logger.debug("langfuse: EVAL_TRACING_ENABLED=false, tracing disabled")
        _client = None
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning(
            "langfuse: EVAL_TRACING_ENABLED=true but PUBLIC/SECRET keys missing; "
            "tracing disabled"
        )
        _client = None
        return None

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("langfuse: initialized client host=%s", settings.langfuse_host)
    except Exception as exc:  # noqa: BLE001
        # Per design Decision 7 + Risks table: trace infra must never block main path.
        logger.warning("langfuse: init failed (%s); tracing disabled", exc)
        _client = None

    return _client


def get_client() -> Any | None:
    """Return the cached client, lazy-initializing on first call."""
    if not _initialized:
        return init_langfuse()
    return _client


def observe(*decorator_args: Any, **decorator_kwargs: Any) -> Callable[[_F], _F]:
    """Re-export of langfuse `@observe` decorator with no-op fallback.

    When tracing is disabled or langfuse is not installed, the decorator
    is a pass-through that returns the wrapped function unchanged.
    """
    # Determine whether the real langfuse decorator should be used.
    if not settings.eval_tracing_enabled:
        return _noop_decorator

    try:
        from langfuse import observe as _real_observe
    except ImportError:
        logger.debug("langfuse: package not installed, observe() is a no-op")
        return _noop_decorator

    return _real_observe(*decorator_args, **decorator_kwargs)


def _noop_decorator(func: _F) -> _F:
    """Identity decorator used when tracing is disabled."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


@asynccontextmanager
async def trace_span(
    span_type: str,
    span_name: str,
    *,
    stage_name: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Async context manager that records a span to PG (dual-sink partner of `@observe`).

    Behavior matrix:

    | EVAL_TRACING_ENABLED | eval_context bound? | Action |
    |----------------------|---------------------|--------|
    | false                | any                 | no-op (yield empty dict, skip write) |
    | true                 | None (prod traffic) | no-op (Langfuse @observe still records) |
    | true                 | bound (eval run)    | record span_id, time, write to PG |

    The yielded dict is the per-span payload. Caller mutates it in place:

        async with trace_span("llm_call", "answer_round_0") as record:
            response = await client.chat.completions.create(...)
            record["llm_model"] = "gpt-4o"
            record["llm_finish_reason"] = response.choices[0].finish_reason
            record["llm_messages_json"] = messages
            record["llm_output_text"] = response.choices[0].message.content

    The context manager fills in span_id, trace_id, parent_span_id, run_id,
    item_id, turn_idx, span_type, span_name, started_at, ended_at, elapsed_ms,
    stage_name on exit, then dispatches to write_span() (best-effort,
    swallows errors per Decision 7).

    Spans nested within a parent `trace_span` inherit parent_span_id from
    the current context (single-level for now; deeper nesting can extend
    this via additional contextvars if needed).
    """
    if not settings.eval_tracing_enabled:
        yield {}
        return

    ctx = get_eval_context()
    if ctx is None:
        # No eval context → prod user traffic. Skip PG sink to avoid noise;
        # Langfuse @observe handles Cloud sink independently.
        yield {}
        return

    # Lazy import to avoid circular dependency at module load.
    from eval.tracing.span_writer import write_span

    started_at = datetime.now(UTC)
    span_id = uuid4()
    parent_span_id = ctx.get("current_parent_span_id")
    record: dict[str, Any] = {}

    try:
        yield record
    finally:
        ended_at = datetime.now(UTC)
        elapsed_ms = int((ended_at - started_at).total_seconds() * 1000)
        full = {
            "span_id": span_id,
            "trace_id": ctx["trace_id"],
            "parent_span_id": parent_span_id,
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
        full.update(record)
        try:
            await write_span(full)
        except Exception as exc:  # noqa: BLE001 — defense in depth
            logger.warning("trace_span: write_span raised unexpectedly (%s)", exc)
