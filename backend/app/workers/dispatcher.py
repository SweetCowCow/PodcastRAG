"""Standalone process: pop pending rows from transcription_queue and
dispatch ``transcribe_episode`` Celery tasks.

Runs an infinite loop with a 1-second sleep. Per design "Dispatcher:
poll-based, not pubsub" — picked over Redis pub/sub for simplicity at
single-show / single-worker scale.

Concurrency safety:
- ``SELECT ... FOR UPDATE SKIP LOCKED`` ensures two dispatcher
  processes never claim the same row.
- Concurrency cap is read from
  ``settings_cache.get_max_concurrent`` so it can be tuned at runtime
  without restart.

Run via:  ``python -m app.workers.dispatcher``
"""
import asyncio
import logging
import signal
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.services.settings_cache import get_max_concurrent
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
_shutdown = False


def _request_shutdown(*_args) -> None:
    global _shutdown
    _shutdown = True
    logger.info("dispatcher: shutdown signal received")


async def _try_pop_one(session) -> str | None:
    """Pick the lowest-position pending row eligible for dispatch.

    celery-routing-and-dispatcher-fix:
    - dispatcher 不再 set status=running / started_at / celery_task_id;
      那三個欄位由 worker task entry 自己 set，DB 狀態才會等於 worker
      實際狀態（stale-detect 30 min 閾值才有意義）。
    - 改寫成「set dispatched_at = NOW() 後 commit、再 send_task」。
    - SELECT 條件加上 ``dispatched_at IS NULL`` + ``FOR UPDATE SKIP LOCKED``
      防 dispatcher 自身 race（連續兩 tick 都選到同 row）以及
      多 dispatcher instance（rolling deploy）同時 claim 同 row。

    concurrency cap 仍以 ``status='running'`` row count 為分母——這現在
    完全等於 worker 真實 in-flight 數量。

    Returns the popped episode_id (str) or None if nothing eligible.
    """
    running_count = await session.scalar(
        select(func.count(TranscriptionQueue.id)).where(
            TranscriptionQueue.status == QueueStatus.running
        )
    )
    max_concurrent = get_max_concurrent()
    if running_count >= max_concurrent:
        return None

    stmt = (
        select(TranscriptionQueue)
        .where(
            TranscriptionQueue.status == QueueStatus.pending,
            TranscriptionQueue.ignored.is_(False),
            TranscriptionQueue.dispatched_at.is_(None),
        )
        .order_by(TranscriptionQueue.position.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None

    # 只 set dispatcher 自己的 memo pad，不動 status/started_at/celery_task_id。
    row.dispatched_at = datetime.now(timezone.utc)
    await session.commit()
    return str(row.episode_id)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("dispatcher: starting (poll interval %.1fs)", POLL_INTERVAL_SECONDS)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        while not _shutdown:
            try:
                async with Session() as session:
                    episode_id = await _try_pop_one(session)
                if episode_id is not None:
                    celery_app.send_task(
                        "app.workers.tasks.transcribe_episode",
                        args=[episode_id],
                    )
                    logger.info("dispatcher: dispatched episode %s", episode_id)
            except Exception:
                logger.exception("dispatcher: tick failed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        await engine.dispose()
        logger.info("dispatcher: stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    asyncio.run(main())
