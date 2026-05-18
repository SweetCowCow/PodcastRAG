"""Service-level circuit breaker for external providers.

Part of `task-failure-monitoring-and-circuit-breaker`. Provides:

- ``is_open(provider_id, task_type=None)`` — fast check, used by Celery
  task entry points before any external I/O.
- ``open(provider_id, reason)`` — atomic transition closed → open. No-op
  if already open (race-safe via UPDATE ... WHERE state='closed').
- ``close(provider_id, by, kind)`` — atomic transition open → closed.
  ``kind`` is one of ``'probe'`` / ``'manual'``.
- ``increment_paused(provider_id)`` — bump paused_task_count when a task
  hits an open breaker and self-retries.
- ``try_fallback(provider_id, payload, model)`` — aihub → OpenAI direct
  fallback, used by worker permanent-error paths for ContentPolicy /
  budget / quota exhaustion.

All state lives in the ``service_circuit_state`` PG row. Atomic UPDATE
with RETURNING is the only safe way to handle concurrent worker /
beat / admin contention.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.service_circuit_state import (
    CircuitState,
    ServiceCircuitState,
)

logger = logging.getLogger(__name__)


# task-failure-monitoring-and-circuit-breaker: aihub → openai direct
# fallback model mapping. None means "no fallback for this model" (e.g.
# Anthropic Claude has no OpenAI equivalent).
AIHUB_TO_OPENAI_MODEL_MAP: dict[str, str | None] = {
    "gpt-5-mini": "gpt-4o-mini",
    "gemini-2.5-flash-lite": "gpt-4o-mini",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4o": "gpt-4o",
    "claude-haiku-4-5-20251001": None,
}


def _new_engine():
    return create_async_engine(settings.database_url, poolclass=NullPool)


async def is_open(provider_id: str, task_type: str | None = None) -> bool:
    """Cheap read: returns True iff the provider's circuit is open.

    ``task_type`` is reserved for v2 per-task-type granularity; v1
    ignores it (all rows have task_type=NULL).
    """
    engine = _new_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(ServiceCircuitState.state).where(
                        ServiceCircuitState.provider_id == provider_id
                    )
                )
            ).scalar_one_or_none()
            return row == CircuitState.open.value
    finally:
        await engine.dispose()


async def open(  # noqa: A001 — shadowing builtins.open is intentional / scoped
    provider_id: str, reason: str = ""
) -> bool:
    """Atomically transition closed → open. Returns True if WE flipped it.

    No-op (returns False) if the breaker was already open or no row
    exists. Uses ``UPDATE ... WHERE state='closed' RETURNING ...`` so
    concurrent third-error callers don't double-open / double-alert.
    """
    engine = _new_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            now = datetime.now(timezone.utc)
            result = await session.execute(
                update(ServiceCircuitState)
                .where(
                    ServiceCircuitState.provider_id == provider_id,
                    ServiceCircuitState.state == CircuitState.closed.value,
                )
                .values(
                    state=CircuitState.open.value,
                    opened_at=now,
                    paused_task_count=0,
                )
                .returning(ServiceCircuitState.provider_id)
            )
            row = result.scalar_one_or_none()
            await session.commit()
            if row is None:
                logger.info(
                    "circuit_breaker.open(%s) noop — already open or missing row",
                    provider_id,
                )
                return False
            logger.warning(
                "circuit_breaker.open(%s) transition closed→open at %s reason=%s",
                provider_id,
                now.isoformat(),
                reason,
            )
            return True
    finally:
        await engine.dispose()


async def close(provider_id: str, by: str, kind: str) -> dict | None:
    """Atomically transition open → closed.

    ``kind`` must be ``'probe'`` (auto recovery via sentinel) or
    ``'manual'`` (admin button). Returns the row snapshot (dict) on
    success or None if no-op (already closed / missing row).

    Side effect: marks affected ``task_failure_log`` rows
    ``recovered_at=NOW()`` (rows whose ``provider_id`` matches and
    ``recovered_at IS NULL`` AND ``failed_at >= opened_at``).
    """
    if kind not in {"probe", "manual"}:
        raise ValueError(f"close() kind must be probe|manual, got {kind!r}")

    engine = _new_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            now = datetime.now(timezone.utc)
            # Snapshot opened_at first so we can scope the failure-log
            # recovered_at backfill to this open window.
            current = (
                await session.execute(
                    select(ServiceCircuitState).where(
                        ServiceCircuitState.provider_id == provider_id
                    )
                )
            ).scalar_one_or_none()
            if current is None or current.state != CircuitState.open.value:
                return None
            opened_at_snapshot = current.opened_at

            values: dict[str, Any] = {
                "state": CircuitState.closed.value,
            }
            if kind == "manual":
                values["manual_resumed_by"] = by
                values["manual_resumed_at"] = now
            # ``last_probe_at`` / ``last_probe_result`` are set by the
            # probe worker itself for kind='probe' (kept separate so
            # ``close()`` stays a single concern).

            result = await session.execute(
                update(ServiceCircuitState)
                .where(
                    ServiceCircuitState.provider_id == provider_id,
                    ServiceCircuitState.state == CircuitState.open.value,
                )
                .values(**values)
                .returning(
                    ServiceCircuitState.provider_id,
                    ServiceCircuitState.state,
                    ServiceCircuitState.opened_at,
                    ServiceCircuitState.paused_task_count,
                    ServiceCircuitState.last_probe_at,
                    ServiceCircuitState.last_probe_result,
                    ServiceCircuitState.manual_resumed_by,
                    ServiceCircuitState.manual_resumed_at,
                )
            )
            row = result.first()
            if row is None:
                await session.rollback()
                return None

            # Mark related task_failure_log rows recovered.
            if opened_at_snapshot is not None:
                await session.execute(
                    text(
                        """
                        UPDATE task_failure_log
                           SET recovered_at = :now
                         WHERE provider_id = :pid
                           AND recovered_at IS NULL
                           AND failed_at >= :opened_at
                        """
                    ),
                    {
                        "now": now,
                        "pid": provider_id,
                        "opened_at": opened_at_snapshot,
                    },
                )
            await session.commit()
            return dict(row._mapping)
    finally:
        await engine.dispose()


async def increment_paused(provider_id: str) -> None:
    """Bump ``paused_task_count`` by 1. Best-effort: errors logged not raised."""
    engine = _new_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                update(ServiceCircuitState)
                .where(ServiceCircuitState.provider_id == provider_id)
                .values(
                    paused_task_count=(
                        ServiceCircuitState.paused_task_count + 1
                    )
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "circuit_breaker.increment_paused(%s) raised", provider_id
        )
    finally:
        await engine.dispose()


async def update_probe_result(
    provider_id: str, *, success: bool, at: datetime | None = None
) -> None:
    """Stamp ``last_probe_at`` / ``last_probe_result`` regardless of state."""
    when = at or datetime.now(timezone.utc)
    engine = _new_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                update(ServiceCircuitState)
                .where(ServiceCircuitState.provider_id == provider_id)
                .values(
                    last_probe_at=when,
                    last_probe_result=("success" if success else "failure"),
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


# ─────────────────────────── Fallback (aihub → OpenAI direct) ───────────────

# Exceptions that trigger the aihub → openai fallback. We import lazily
# inside the function to avoid hard-importing openai/httpx at module
# load time (keeps tests fast and import-clean).
_FALLBACK_TRIGGER_NAMES: frozenset[str] = frozenset(
    {
        "app.services.exceptions.ContentPolicyViolationError",
        "app.services.exceptions.BudgetExceededError",
        "app.services.exceptions.InsufficientQuotaError",
    }
)


def is_fallback_trigger(exc: BaseException) -> bool:
    """Whether ``exc`` is one of the three aihub fallback trigger types."""
    from app.services import error_classifier  # local import

    for cls in type(exc).__mro__:
        if error_classifier._full_class_name(cls) in _FALLBACK_TRIGGER_NAMES:
            return True
    return False


def resolve_openai_fallback_model(aihub_model: str) -> str | None:
    """Return the OpenAI direct model to use, or None if no mapping."""
    return AIHUB_TO_OPENAI_MODEL_MAP.get(aihub_model)


async def with_aihub_fallback(
    call_fn,
    *,
    task_name: str,
    task_args,
    model: str,
    payload: dict,
):
    """Decorator-style helper: run ``call_fn()``; if it raises one of the
    fallback-trigger exception types, try the OpenAI direct fallback.

    Returns ``(result, used_fallback: bool)``. When fallback succeeds,
    the original aihub failure is written to ``task_failure_log`` with
    ``failure_type='transient'`` + ``recovered_at=NOW()`` and the call
    returns normally. When fallback fails, BOTH failures are recorded
    (aihub + openai) and the original exception is re-raised so Celery
    sees the failure.

    ``call_fn`` is an async callable that issues the aihub LLM request.
    ``payload`` is the request kwargs to retry against OpenAI direct.
    """
    from datetime import datetime, timezone

    from app.services.failure_log import write_failure_log
    from app.models.task_failure_log import FailureType

    try:
        result = await call_fn()
        return result, False
    except Exception as exc:
        if not is_fallback_trigger(exc):
            raise
        fallback_model = resolve_openai_fallback_model(model)
        if fallback_model is None:
            # No mapping → cannot fallback; record permanent + re-raise.
            raise

        fallback_resp, ok = await try_fallback(
            "aihub", payload=payload, model=model
        )
        if ok:
            # Recovered — record aihub as transient + recovered.
            await write_failure_log(
                task_name=task_name,
                args=task_args,
                exc=exc,
                provider_id="aihub",
                retry_count=0,
                force_failure_type=FailureType.transient,
                error_message_override=(
                    f"aihub {type(exc).__name__}: {str(exc)[:200]}; "
                    "recovered via fallback"
                ),
                recovered_at=datetime.now(timezone.utc),
            )
            return fallback_resp, True

        # Fallback also failed → two failure rows (aihub + openai),
        # each counts toward its own breaker threshold.
        await write_failure_log(
            task_name=task_name,
            args=task_args,
            exc=exc,
            provider_id="aihub",
            retry_count=0,
        )
        # Synthesise an exception for the openai-side failure so the
        # second log row is distinguishable.
        openai_exc = RuntimeError(
            f"openai direct fallback failed (model={fallback_model})"
        )
        await write_failure_log(
            task_name=task_name,
            args=task_args,
            exc=openai_exc,
            provider_id="openai",
            retry_count=0,
        )
        # Re-raise the original so Celery records FAILURE.
        raise


async def try_fallback(
    provider_id: str,
    payload: dict,
    model: str,
) -> tuple[Any | None, bool]:
    """Attempt one OpenAI direct fallback call for an aihub permanent error.

    Returns ``(response, True)`` on success, ``(None, False)`` if fallback
    is unavailable (provider != aihub / unknown model / API key missing)
    OR if the OpenAI call itself fails.

    Caller is responsible for re-emitting the request payload — this
    helper just dispatches to ``openai.OpenAI()`` with the resolved model.
    """
    if provider_id != "aihub":
        return None, False
    fallback_model = resolve_openai_fallback_model(model)
    if fallback_model is None:
        logger.info(
            "circuit_breaker.try_fallback: no mapping for aihub model %s",
            model,
        )
        return None, False

    # Resolve the OpenAI direct key. Centralised here so callers don't
    # leak the key-resolution shape.
    api_key = await _resolve_openai_direct_key()
    if not api_key:
        logger.warning(
            "circuit_breaker.try_fallback: no OpenAI direct key configured"
        )
        return None, False

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        fallback_payload = {**payload, "model": fallback_model}
        response = await client.chat.completions.create(**fallback_payload)
        logger.warning(
            "circuit_breaker.try_fallback: aihub→openai fallback succeeded "
            "(model %s → %s)",
            model,
            fallback_model,
        )
        return response, True
    except Exception:
        logger.exception(
            "circuit_breaker.try_fallback: openai direct call failed "
            "(aihub model=%s fallback=%s)",
            model,
            fallback_model,
        )
        return None, False


async def _resolve_openai_direct_key() -> str | None:
    """Look up the OpenAI direct API key.

    Per project memory note: ``OPENAI_API_KEY`` env is actually the
    AI Hub key; the real OpenAI direct key lives in the ``api_keys``
    DB table. We try DB first, then fall back to env to keep tests
    happy without a DB row.
    """
    try:
        from app.models.api_key import ApiKey

        engine = _new_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = (
                    await session.execute(
                        select(ApiKey.api_key)
                        .where(ApiKey.provider == "openai")
                        .order_by(ApiKey.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if row:
                    return row
        finally:
            await engine.dispose()
    except Exception:
        logger.exception(
            "circuit_breaker._resolve_openai_direct_key: DB lookup failed"
        )

    return settings.openai_api_key if hasattr(settings, "openai_api_key") else None
