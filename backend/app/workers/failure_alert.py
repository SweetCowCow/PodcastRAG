"""Beat-driven sliding-window failure rate alert.

Part of `task-failure-monitoring-and-circuit-breaker`. Runs every 5 min
(see ``celery_app.beat_schedule['failure-alert']``). For each ``task_name``
with ≥3 rows in the last 30 min where ``alerted_at IS NULL``, send one
ZSend email and stamp ``alerted_at = NOW()`` so the same batch isn't
re-alerted on the next tick.

Also responsible for the daily ``task_failure_log`` cleanup (rows older
than 30 days). Cleanup runs only at the 4-AM-UTC tick so we don't pay
for it every 5 min.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.task_failure_log import TaskFailureLog
from app.services.zsend import ZSendError, send_failure_alert
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

ALERT_WINDOW_MINUTES = 30
ALERT_THRESHOLD = 3
CLEANUP_RETENTION_DAYS = 30


def _new_engine():
    return create_async_engine(settings.database_url, poolclass=NullPool)


def _to_taipei(ts: datetime) -> str:
    if ts is None:
        return "—"
    taipei = ts.astimezone(timezone(timedelta(hours=8)))
    return taipei.strftime("%Y-%m-%d %H:%M:%S")


@celery_app.task(name="app.workers.failure_alert.run_failure_alert")
def run_failure_alert() -> dict:
    """Beat entry — see module docstring."""
    return asyncio.run(_run())


async def _run() -> dict:
    if not settings.zsend_api_key:
        logger.info(
            "failure_alert: ZSend not configured, skipping alert"
        )
        # Still run cleanup since it's DB-only.
        cleaned = await _cleanup_old_rows_if_due()
        return {"sent": 0, "skipped": "zsend_unconfigured", "cleaned": cleaned}

    sent_count = 0
    engine = _new_engine()
    try:
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=ALERT_WINDOW_MINUTES
        )

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            # Find task_names with ≥3 rows in window AND alerted_at IS NULL.
            stmt = (
                select(
                    TaskFailureLog.task_name,
                    func.count().label("n"),
                )
                .where(
                    TaskFailureLog.failed_at >= window_start,
                    TaskFailureLog.alerted_at.is_(None),
                )
                .group_by(TaskFailureLog.task_name)
                .having(func.count() >= ALERT_THRESHOLD)
            )
            rows = (await session.execute(stmt)).all()

        for task_name, n in rows:
            # Pull the qualifying rows for this task_name (for context +
            # alerted_at update).
            async with async_sessionmaker(
                engine, expire_on_commit=False
            )() as session:
                detail = (
                    await session.execute(
                        select(TaskFailureLog)
                        .where(
                            TaskFailureLog.task_name == task_name,
                            TaskFailureLog.failed_at >= window_start,
                            TaskFailureLog.alerted_at.is_(None),
                        )
                        .order_by(TaskFailureLog.failed_at.desc())
                    )
                ).scalars().all()

            errors = [r.error_message for r in detail[:3]]
            taipei_ts = [_to_taipei(r.failed_at) for r in detail[:3]]
            by_provider: dict[str, int] = {}
            for r in detail:
                key = r.provider_id or ""
                by_provider[key] = by_provider.get(key, 0) + 1

            try:
                await send_failure_alert(
                    task_name=task_name,
                    count=n,
                    errors=errors,
                    taipei_ts=taipei_ts,
                    by_provider=by_provider,
                )
            except ZSendError:
                # Transient → leave alerted_at NULL so next tick retries.
                logger.warning(
                    "failure_alert: ZSend send failed for %s — will retry next tick",
                    task_name,
                )
                continue
            except Exception:
                logger.exception(
                    "failure_alert: unexpected send error for %s", task_name
                )
                continue

            # Stamp alerted_at on the batch.
            ids = [r.id for r in detail]
            async with async_sessionmaker(
                engine, expire_on_commit=False
            )() as session:
                await session.execute(
                    update(TaskFailureLog)
                    .where(TaskFailureLog.id.in_(ids))
                    .values(alerted_at=datetime.now(timezone.utc))
                )
                await session.commit()
            sent_count += 1
    finally:
        await engine.dispose()

    cleaned = await _cleanup_old_rows_if_due()
    return {"sent": sent_count, "cleaned": cleaned}


async def _cleanup_old_rows_if_due() -> int:
    """Delete ``task_failure_log`` rows older than retention.

    Runs only when current UTC hour == 4 to keep the per-5-min tick cheap.
    Returns rows deleted (0 if not the cleanup hour).
    """
    now = datetime.now(timezone.utc)
    if now.hour != 4:
        return 0
    cutoff = now - timedelta(days=CLEANUP_RETENTION_DAYS)
    engine = _new_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await session.execute(
                delete(TaskFailureLog).where(
                    TaskFailureLog.failed_at < cutoff
                )
            )
            await session.commit()
            return int(result.rowcount or 0)
    finally:
        await engine.dispose()
