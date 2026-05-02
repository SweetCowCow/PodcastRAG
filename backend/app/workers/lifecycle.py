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
import threading
import uuid

from celery.signals import worker_ready, worker_shutting_down
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.celery_app import celery_app
from app.workers.throttle import release_global_slot

logger = logging.getLogger(__name__)

INSPECT_TIMEOUT_SECONDS = 5

_active_row_ids: set[str] = set()
_active_lock = threading.Lock()


def register_active_row(row_id: str) -> None:
    """Mark a queue row as actively processed by this worker process."""
    with _active_lock:
        _active_row_ids.add(row_id)


def deregister_active_row(row_id: str) -> None:
    """Drop a queue row from the active set (task finished or failed)."""
    with _active_lock:
        _active_row_ids.discard(row_id)


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
    if active is None and reserved is None:
        logger.warning(
            "lifecycle: celery inspect returned no workers — conservative mode"
        )
        return set(), False
    active = active or {}
    reserved = reserved or {}
    ids: set[str] = set()
    for tasks in active.values():
        ids.update(t.get("id") for t in (tasks or []) if t.get("id"))
    for tasks in reserved.values():
        ids.update(t.get("id") for t in (tasks or []) if t.get("id"))
    return ids, True


async def _revert_orphan_rows_async(
    active_task_ids: set[str], inspect_succeeded: bool
) -> int:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    reverted = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                await session.execute(
                    select(TranscriptionQueue).where(
                        TranscriptionQueue.status == QueueStatus.running
                    )
                )
            ).scalars().all()
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
    active_task_ids: set[str], inspect_succeeded: bool
) -> int:
    """Scan running rows, revert orphans to pending. Returns revert count.

    Orphan rule:
    - inspect_succeeded=True: row is orphan if ``celery_task_id`` is NULL
      or not in ``active_task_ids``.
    - inspect_succeeded=False: conservative — only NULL task id rows are
      reverted; non-null rows are left for stale-running detection.
    """
    return asyncio.run(
        _revert_orphan_rows_async(active_task_ids, inspect_succeeded)
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


@worker_ready.connect
def _on_worker_ready(sender=None, **kwargs):
    try:
        active_ids, ok = _inspect_active_task_ids()
        n = _revert_orphan_rows(active_ids, ok)
        if n:
            logger.info("lifecycle: worker_ready reverted %d orphan rows", n)
    except Exception:
        logger.exception("lifecycle: worker_ready handler raised")


@worker_shutting_down.connect
def _on_worker_shutdown(sig=None, how=None, exitcode=None, **kwargs):
    try:
        with _active_lock:
            ids = set(_active_row_ids)
        if ids:
            n = asyncio.run(_revert_specific_rows_async(ids))
            if n:
                logger.info(
                    "lifecycle: worker_shutting_down reverted %d running rows",
                    n,
                )
    except Exception:
        logger.exception("lifecycle: worker_shutting_down handler raised")
