"""Tests for transcribe_episode worker entry claim routine.

celery-routing-and-dispatcher-fix:
- 舊行為 `_write_celery_task_id` 已被 `_claim_queue_row` 取代。
- pending row → CLAIM_PROCEED，set running + started_at + celery_task_id。
- cancelled row → CLAIM_SKIP_TERMINAL，不動 row（不再寫 task_id 進 cancelled row）。
"""
import socket
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.tasks import CLAIM_PROCEED, CLAIM_SKIP_TERMINAL, _claim_queue_row
from tests.conftest import _postgres_reachable


def _db_connectable() -> bool:
    if not _postgres_reachable():
        return False
    try:
        import asyncio
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.core.config import settings

        async def _check():
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.connect():
                    return True
            finally:
                await engine.dispose()

        return asyncio.run(_check())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_connectable(), reason="local postgres + DATABASE_URL required"
)


@pytest_asyncio.fixture
async def queue_row():
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Cancel Test Show",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()

        episode = Episode(
            show_id=show.id,
            guid=str(uuid.uuid4()),
            title="Ep 1",
            audio_url="https://example.com/a.mp3",
        )
        db.add(episode)
        await db.flush()

        row = TranscriptionQueue(
            episode_id=episode.id,
            show_id=show.id,
            status=QueueStatus.pending,
            position=999999,
            whisper_model="whisper-1",
        )
        db.add(row)
        await db.commit()

        ids = (str(row.id), str(episode.id), str(show.id))

    yield ids

    async with AsyncSessionFactory() as db:
        await db.execute(
            delete(TranscriptionQueue).where(TranscriptionQueue.id == uuid.UUID(ids[0]))
        )
        await db.execute(delete(Episode).where(Episode.id == uuid.UUID(ids[1])))
        await db.execute(delete(Show).where(Show.id == uuid.UUID(ids[2])))
        await db.commit()


@pytest.mark.asyncio
async def test_claim_pending_row_transitions_to_running(queue_row):
    """Pending row → CLAIM_PROCEED + set running + celery_task_id + started_at."""
    queue_id, episode_id, _ = queue_row
    claim, row_id = await _claim_queue_row(episode_id, "task-abc-123")
    assert claim == CLAIM_PROCEED
    assert row_id == queue_id

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(queue_id))
        assert row.celery_task_id == "task-abc-123"
        assert row.status == QueueStatus.running
        assert row.started_at is not None
        assert row.dispatched_at is None


@pytest.mark.asyncio
async def test_cancelled_row_is_acked_without_modification(queue_row):
    """Cancelled row → CLAIM_SKIP_TERMINAL，不寫 task_id、不改 status。"""
    queue_id, episode_id, _ = queue_row

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(queue_id))
        row.status = QueueStatus.cancelled
        await db.commit()

    claim, row_id = await _claim_queue_row(episode_id, "task-xyz-999")
    assert claim == CLAIM_SKIP_TERMINAL
    assert row_id == queue_id

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(queue_id))
        assert row.celery_task_id is None
        assert row.status == QueueStatus.cancelled
