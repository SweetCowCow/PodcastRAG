"""Enqueue API used by manual triggers (HTTP handlers, cron tick).

After the DB-driven queue refactor the source of truth is the
``transcription_queue`` table — the dispatcher process reads from there
and dispatches to Celery. Enqueueing now means: insert (or revive) a
queue row.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.episode import Episode
from app.models.transcription_queue import QueueStatus, TranscriptionQueue


async def enqueue_transcription(
    episode_id: uuid.UUID, db: AsyncSession | None = None
) -> str:
    """Insert (or revive) a queue row for ``episode_id`` and return its id.

    Behaviour per the transcription-queue spec:
    - If no row exists, INSERT a new one with status=pending and
      ``position = MAX(position) + 1``.
    - If a row exists with status in (completed, failed, cancelled),
      revive it: status=pending, new position, started_at=null,
      finished_at=null, error_message=null.
    - If a row exists with status in (pending, running), leave it
      alone and return its id.

    Pass ``db`` when calling from inside an existing async session
    (e.g. an HTTP handler) so the operation joins that transaction.
    Omit it from standalone scripts to get a one-off engine + commit.
    """
    if db is not None:
        return await _enqueue_in(db, episode_id, owns_commit=False)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await _enqueue_in(session, episode_id, owns_commit=True)
    finally:
        await engine.dispose()


async def _enqueue_in(
    session: AsyncSession, episode_id: uuid.UUID, owns_commit: bool
) -> str:
    existing = (
        await session.execute(
            select(TranscriptionQueue).where(
                TranscriptionQueue.episode_id == episode_id
            )
        )
    ).scalar_one_or_none()

    if existing is not None and existing.status in (
        QueueStatus.pending,
        QueueStatus.running,
    ):
        return str(existing.id)

    if existing is not None and existing.ignored:
        # Per transcription-queue spec: ignored rows MUST NOT be revived
        # by re-enqueue (whether triggered manually or by cron tick).
        return str(existing.id)

    episode = await session.get(Episode, episode_id)
    if episode is None:
        raise ValueError(f"Episode {episode_id} 不存在")

    next_position = (
        await session.scalar(
            select(func.coalesce(func.max(TranscriptionQueue.position), 0))
        )
    ) + 1

    if existing is None:
        row = TranscriptionQueue(
            episode_id=episode_id,
            show_id=episode.show_id,
            status=QueueStatus.pending,
            position=next_position,
            whisper_model="large-v3",
        )
        session.add(row)
        if owns_commit:
            await session.commit()
        else:
            await session.flush()
        await session.refresh(row)
        return str(row.id)

    existing.status = QueueStatus.pending
    existing.position = next_position
    existing.started_at = None
    existing.finished_at = None
    existing.error_message = None
    existing.celery_task_id = None
    if owns_commit:
        await session.commit()
    else:
        await session.flush()
    return str(existing.id)
