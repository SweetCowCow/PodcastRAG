"""Celery worker lifecycle handlers.

Two responsibilities:

1. ``worker_ready`` — at startup, scan ``transcription_queue`` for rows
   left in ``status=running`` by a previously crashed/killed worker and
   revert them to ``pending`` so the dispatcher can re-queue them.
2. ``worker_shutting_down`` — at SIGTERM (deploy), revert any rows this
   worker is currently processing to ``pending`` so the next worker
   picks them up immediately instead of waiting for stale-running
   detection (30 min cron).

Both paths also free the matching throttle slot so the global active
counter reflects reality.
"""
import asyncio
import logging
import uuid

from celery.signals import worker_ready, worker_shutting_down
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.celery_app import celery_app
from app.workers.throttle import _get_redis, release_global_slot

logger = logging.getLogger(__name__)

INSPECT_TIMEOUT_SECONDS = 5

ACTIVE_ROWS_KEY = "transcribe:worker:active_rows"


def register_active_row(row_id: str) -> None:
    """Mark a queue row as actively processed by this worker.

    Stored in Redis (not in-memory) because Celery prefork workers run
    tasks in forked child processes whose memory is not visible to the
    main process where ``worker_shutting_down`` fires. A shared Redis
    set lets the shutdown handler see what every fork child registered.
    """
    try:
        _get_redis().sadd(ACTIVE_ROWS_KEY, row_id)
    except Exception:
        logger.exception("lifecycle: register_active_row failed for %s", row_id)


def deregister_active_row(row_id: str) -> None:
    """Drop a queue row from the active set (task finished or failed)."""
    try:
        _get_redis().srem(ACTIVE_ROWS_KEY, row_id)
    except Exception:
        logger.exception("lifecycle: deregister_active_row failed for %s", row_id)


def _inspect_active_task_ids() -> tuple[set[str], bool]:
    """Query Celery for currently active+reserved task ids across workers.

    Returns ``(task_ids, succeeded)``. On timeout / exception / no workers
    responding, returns ``(empty_set, False)`` so callers can fall back to
    conservative recovery (only revert rows with NULL task id).
    """
    try:
        inspect = celery_app.control.inspect(timeout=INSPECT_TIMEOUT_SECONDS)
        active = inspect.active()
        reserved = inspect.reserved()
    except Exception:
        logger.warning(
            "lifecycle: celery inspect raised — conservative mode", exc_info=True
        )
        return set(), False
    active = active or {}
    reserved = reserved or {}
    if not active and not reserved:
        logger.warning(
            "lifecycle: celery inspect returned no workers — conservative mode"
        )
        return set(), False
    ids: set[str] = set()
    for tasks in active.values():
        ids.update(t.get("id") for t in (tasks or []) if t.get("id"))
    for tasks in reserved.values():
        ids.update(t.get("id") for t in (tasks or []) if t.get("id"))
    return ids, True


async def _revert_orphan_rows_async(
    active_task_ids: set[str],
    inspect_succeeded: bool,
    min_started_at_age_seconds: int = 0,
) -> int:
    """Scan running rows, revert orphans to pending. Returns revert count.

    ``min_started_at_age_seconds`` skips rows whose ``started_at`` is more
    recent than the threshold — prevents racing with newly-dispatched
    tasks that haven't appeared in ``inspect.active()`` yet.
    """
    from datetime import datetime, timedelta, timezone

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    reverted = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stmt = select(TranscriptionQueue).where(
                TranscriptionQueue.status == QueueStatus.running
            )
            if min_started_at_age_seconds > 0:
                cutoff = datetime.now(timezone.utc) - timedelta(
                    seconds=min_started_at_age_seconds
                )
                stmt = stmt.where(
                    TranscriptionQueue.started_at.is_(None)
                    | (TranscriptionQueue.started_at < cutoff)
                )
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                if not inspect_succeeded:
                    if row.celery_task_id is not None:
                        continue
                else:
                    if (
                        row.celery_task_id is not None
                        and row.celery_task_id in active_task_ids
                    ):
                        continue
                row.status = QueueStatus.pending
                row.started_at = None
                row.celery_task_id = None
                row.error_message = None
                try:
                    release_global_slot(str(row.id))
                except Exception:
                    logger.exception(
                        "lifecycle: release_global_slot failed for queue_id=%s",
                        row.id,
                    )
                reverted += 1
            if reverted:
                await session.commit()
    finally:
        await engine.dispose()
    return reverted


def _revert_orphan_rows(
    active_task_ids: set[str],
    inspect_succeeded: bool,
    min_started_at_age_seconds: int = 0,
) -> int:
    """Sync wrapper; see ``_revert_orphan_rows_async`` for semantics."""
    return asyncio.run(
        _revert_orphan_rows_async(
            active_task_ids, inspect_succeeded, min_started_at_age_seconds
        )
    )


async def _revert_specific_rows_async(row_ids: set[str]) -> int:
    if not row_ids:
        return 0
    uuid_set = {uuid.UUID(rid) for rid in row_ids}
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    reverted = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                await session.execute(
                    select(TranscriptionQueue).where(
                        TranscriptionQueue.id.in_(uuid_set),
                        TranscriptionQueue.status == QueueStatus.running,
                    )
                )
            ).scalars().all()
            for row in rows:
                row.status = QueueStatus.pending
                row.started_at = None
                row.celery_task_id = None
                row.error_message = None
                try:
                    release_global_slot(str(row.id))
                except Exception:
                    logger.exception(
                        "lifecycle: release_global_slot failed for queue_id=%s",
                        row.id,
                    )
                reverted += 1
            if reverted:
                await session.commit()
    finally:
        await engine.dispose()
    return reverted


async def _revert_dispatcher_marked_rows_async() -> int:
    """celery-routing-and-dispatcher-fix migration cutover hook.

    Old dispatcher used to set status=running with started_at=NOW() and
    later sometimes started_at=NULL during transitional bugs. New
    dispatcher does NOT set status=running at all. Any row left in the
    legacy state ``status=running AND started_at IS NULL`` after the
    cutover is a ghost — reset it to pending so the new flow can re-pick.

    This is conservative: rows with started_at set (even old) go through
    the existing orphan-revert / stale-detect paths instead.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    reverted = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                await session.execute(
                    select(TranscriptionQueue).where(
                        TranscriptionQueue.status == QueueStatus.running,
                        TranscriptionQueue.started_at.is_(None),
                    )
                )
            ).scalars().all()
            for row in rows:
                row.status = QueueStatus.pending
                row.started_at = None
                row.celery_task_id = None
                row.error_message = None
                try:
                    release_global_slot(str(row.id))
                except Exception:
                    logger.exception(
                        "lifecycle: release_global_slot failed for queue_id=%s",
                        row.id,
                    )
                reverted += 1
            if reverted:
                await session.commit()
    finally:
        await engine.dispose()
    return reverted


@worker_ready.connect
def _on_worker_ready(sender=None, **kwargs):
    try:
        # celery-routing-and-dispatcher-fix: 先清掉 dispatcher 改寫前留下的
        # status=running + started_at IS NULL ghost row，再跑既有 orphan-revert。
        try:
            n_legacy = asyncio.run(_revert_dispatcher_marked_rows_async())
            if n_legacy:
                logger.info(
                    "lifecycle: worker_ready — reset %d dispatcher-marked rows "
                    "(status=running, started_at IS NULL)",
                    n_legacy,
                )
        except Exception:
            logger.exception(
                "lifecycle: worker_ready dispatcher-marked reset failed"
            )

        active_ids, ok = _inspect_active_task_ids()
        n = _revert_orphan_rows(active_ids, ok)
        logger.info(
            "lifecycle: worker_ready — reverted %d orphan rows (inspect_ok=%s)",
            n,
            ok,
        )
    except Exception:
        logger.exception("lifecycle: worker_ready handler raised")


@worker_shutting_down.connect
def _on_worker_shutdown(sig=None, how=None, exitcode=None, **kwargs):
    try:
        try:
            raw = _get_redis().smembers(ACTIVE_ROWS_KEY)
        except Exception:
            logger.exception("lifecycle: reading active rows from redis failed")
            return
        ids = {b.decode() if isinstance(b, bytes) else b for b in (raw or set())}
        logger.info(
            "lifecycle: worker_shutting_down received — %d active rows tracked",
            len(ids),
        )
        if ids:
            n = asyncio.run(_revert_specific_rows_async(ids))
            try:
                _get_redis().srem(ACTIVE_ROWS_KEY, *ids)
            except Exception:
                logger.exception(
                    "lifecycle: clearing active rows set in redis failed"
                )
            logger.info(
                "lifecycle: worker_shutting_down reverted %d running rows", n
            )
    except Exception:
        logger.exception("lifecycle: worker_shutting_down handler raised")
