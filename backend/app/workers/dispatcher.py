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
    """Pop the lowest-position pending row and send to Celery broker.

    celery-routing-and-dispatcher-fix:
    - Dispatcher 不再 set status=running / started_at / celery_task_id。
      這些欄位 defer 給 worker task entry 的 idempotency routine 處理，
      確保 DB status 真正反映 worker 狀態（stale-detect 才不會被騙）。
    - Concurrency cap 仍以 `status='running'` row count 為分母（即真正被
      worker pick up 的 row），dispatcher 只送 task，不預先佔位。
    - 因為不再 update row，這裡用一般 SELECT 即可；下一輪 poll 看到同一
      row 仍 pending 也沒關係（worker entry 的 SELECT FOR UPDATE 會
      做唯一性檢查）。Celery broker priority 會避免短時間內無限 enqueue。

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
        )
        .order_by(TranscriptionQueue.position.asc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None

    # No DB write — worker entry transitions row to running atomically.
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
