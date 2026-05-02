"""Tests for transcribe_episode worker writing celery_task_id and honouring
force-cancel arrivals (covers parallel-transcription-and-force-cancel
spec scenarios in transcription-queue)."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.tasks import _write_celery_task_id


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
            status=QueueStatus.running,
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
async def test_write_celery_task_id_on_running_row(queue_row):
    """Worker writes celery_task_id at task start; row remains running."""
    queue_id, episode_id, _ = queue_row
    early_exit = await _write_celery_task_id(episode_id, "task-abc-123")
    assert early_exit is False

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(queue_id))
        assert row.celery_task_id == "task-abc-123"
        assert row.status == QueueStatus.running


@pytest.mark.asyncio
async def test_cancelled_before_worker_starts_signals_early_exit(queue_row):
    """If row is cancelled before worker writes task_id, _write_celery_task_id
    SHALL still write task_id but signal early-exit so caller skips processing."""
    queue_id, episode_id, _ = queue_row

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(queue_id))
        row.status = QueueStatus.cancelled
        await db.commit()

    early_exit = await _write_celery_task_id(episode_id, "task-xyz-999")
    assert early_exit is True

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(queue_id))
        assert row.celery_task_id == "task-xyz-999"
        assert row.status == QueueStatus.cancelled
