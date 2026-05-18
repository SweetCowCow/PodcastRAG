"""Persist Celery task failure events + trigger the circuit breaker.

Part of `task-failure-monitoring-and-circuit-breaker`. Single entry-point
``write_failure_log`` is called from each Celery task's
``Task.on_failure`` (or the permanent-error short-circuit branch).

Responsibilities:

1. Classify the exception via ``error_classifier.classify`` and write
   one row into ``task_failure_log``.
2. When the row is ``failure_type='permanent'`` with a non-NULL
   ``provider_id``, evaluate the "≥3 permanent errors for this provider
   in the last 5 min" rule and, if it trips, atomically transition the
   circuit to ``open`` + send a ZSend "circuit opened" email.

The function is best-effort: any internal error is logged but never
re-raised, because raising from ``on_failure`` would mask the original
task exception and confuse Celery's accounting.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.task_failure_log import FailureType, TaskFailureLog
from app.services import circuit_breaker, error_classifier

logger = logging.getLogger(__name__)


ERROR_MESSAGE_MAX_LEN = 4000  # ~4KB per spec
CIRCUIT_PERMANENT_THRESHOLD = 3
CIRCUIT_WINDOW_MINUTES = 5


def _safe_json_args(args: object) -> object | None:
    """Best-effort jsonify task args; return None on failure."""
    if args is None:
        return None
    try:
        json.dumps(args, default=str)
        return args
    except (TypeError, ValueError):
        try:
            return json.loads(json.dumps(args, default=str))
        except Exception:
            return None


def _new_engine():
    return create_async_engine(settings.database_url, poolclass=NullPool)


async def write_failure_log(
    task_name: str,
    args: object,
    exc: BaseException,
    provider_id: str | None = None,
    retry_count: int = 0,
    *,
    force_failure_type: FailureType | str | None = None,
    error_message_override: str | None = None,
    recovered_at: datetime | None = None,
) -> uuid.UUID | None:
    """Insert one row into ``task_failure_log`` and maybe open the breaker.

    Returns the new row id, or None if the write itself failed.

    ``force_failure_type`` lets the fallback path mark a row as
    ``transient`` + supply ``recovered_at`` ("recovered via fallback")
    even though the underlying exception is permanent.
    """
    try:
        if force_failure_type is None:
            failure_type_value = error_classifier.classify(exc)
        elif isinstance(force_failure_type, FailureType):
            failure_type_value = force_failure_type.value
        else:
            failure_type_value = str(force_failure_type)

        error_class = type(exc).__name__
        msg_source = (
            error_message_override if error_message_override is not None else str(exc)
        )
        error_message = msg_source[:ERROR_MESSAGE_MAX_LEN]
        args_json = _safe_json_args(args)

        engine = _new_engine()
        row_id: uuid.UUID | None = None
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = TaskFailureLog(
                    task_name=task_name,
                    task_args_json=args_json,
                    failure_type=failure_type_value,
                    error_class=error_class,
                    error_message=error_message,
                    provider_id=provider_id,
                    retry_count=retry_count,
                    recovered_at=recovered_at,
                )
                session.add(row)
                await session.commit()
                row_id = row.id
        finally:
            await engine.dispose()

        if (
            failure_type_value == FailureType.permanent.value
            and provider_id
            and recovered_at is None
        ):
            await _maybe_open_circuit(provider_id, exc)

        return row_id
    except Exception:
        logger.exception(
            "failure_log.write_failure_log raised for task=%s provider=%s",
            task_name,
            provider_id,
        )
        return None


async def _maybe_open_circuit(provider_id: str, exc: BaseException) -> None:
    """Check threshold + open breaker if exceeded. Send ZSend on transition."""
    try:
        engine = _new_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(
                    minutes=CIRCUIT_WINDOW_MINUTES
                )
                count = (
                    await session.execute(
                        select(func.count())
                        .select_from(TaskFailureLog)
                        .where(
                            TaskFailureLog.provider_id == provider_id,
                            TaskFailureLog.failure_type
                            == FailureType.permanent.value,
                            TaskFailureLog.failed_at >= cutoff,
                        )
                    )
                ).scalar_one()
        finally:
            await engine.dispose()

        if count < CIRCUIT_PERMANENT_THRESHOLD:
            return

        # Try to flip closed → open atomically. Returns False if a
        # concurrent worker already opened it.
        opened = await circuit_breaker.open(
            provider_id, reason=f"{type(exc).__name__}: {str(exc)[:200]}"
        )
        if not opened:
            return

        # Send ZSend "circuit opened" email. Best-effort.
        try:
            from app.services.zsend import send_circuit_opened_alert

            await send_circuit_opened_alert(
                provider_id=provider_id,
                latest_error=f"{type(exc).__name__}: {str(exc)[:300]}",
                failure_count=count,
            )
        except Exception:
            logger.exception(
                "failure_log: ZSend circuit-opened alert failed for %s",
                provider_id,
            )
    except Exception:
        logger.exception(
            "failure_log._maybe_open_circuit raised for %s", provider_id
        )
