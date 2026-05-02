"""Tests for worker startup self-recovery: _revert_orphan_rows_async behaviour
across (NULL task id / unknown task id / live task id) × (inspect ok /
inspect failed) combinations.
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
from app.workers.lifecycle import _revert_orphan_rows_async
from tests.conftest import _postgres_reachable


def _redis_reachable() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", 6379))
        return True
    except OSError:
        return False
    finally:
        s.close()


pytestmark = pytest.mark.skipif(
    not (_postgres_reachable() and _redis_reachable()),
    reason="local postgres and redis required",
)


@pytest_asyncio.fixture
async def make_running_row():
    created: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    async def _make(celery_task_id: str | None) -> str:
        async with AsyncSessionFactory() as db:
            show = Show(
                title="Lifecycle Test",
                rss_url=f"https://example.com/rss/{uuid.uuid4()}",
                language="zh-tw",
            )
            db.add(show)
            await db.flush()
            episode = Episode(
                show_id=show.id,
                guid=str(uuid.uuid4()),
                title="Ep",
                audio_url="https://example.com/a.mp3",
            )
            db.add(episode)
            await db.flush()
            row = TranscriptionQueue(
                episode_id=episode.id,
                show_id=show.id,
                status=QueueStatus.running,
                position=999700 + len(created),
                whisper_model="whisper-1",
                celery_task_id=celery_task_id,
            )
            db.add(row)
            await db.commit()
            created.append((row.id, episode.id, show.id))
            return str(row.id)

    yield _make

    async with AsyncSessionFactory() as db:
        for row_id, ep_id, show_id in created:
            await db.execute(
                delete(TranscriptionQueue).where(TranscriptionQueue.id == row_id)
            )
            await db.execute(delete(Episode).where(Episode.id == ep_id))
            await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


async def _fetch_status(row_id: str) -> QueueStatus:
    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        return row.status


@pytest.mark.asyncio
async def test_revert_orphan_rows_null_task_id(make_running_row):
    row_id = await make_running_row(celery_task_id=None)
    await _revert_orphan_rows_async(set(), True)
    assert await _fetch_status(row_id) == QueueStatus.pending


@pytest.mark.asyncio
async def test_revert_orphan_rows_task_not_in_active(make_running_row):
    row_id = await make_running_row(celery_task_id="ghost-task")
    await _revert_orphan_rows_async({"live-task"}, True)
    assert await _fetch_status(row_id) == QueueStatus.pending


@pytest.mark.asyncio
async def test_revert_preserves_active_task(make_running_row):
    row_id = await make_running_row(celery_task_id="live-task")
    await _revert_orphan_rows_async({"live-task"}, True)
    assert await _fetch_status(row_id) == QueueStatus.running


@pytest.mark.asyncio
async def test_inspect_failure_conservative(make_running_row):
    null_row_id = await make_running_row(celery_task_id=None)
    unknown_row_id = await make_running_row(celery_task_id="unknown-task")
    await _revert_orphan_rows_async(set(), False)
    assert await _fetch_status(null_row_id) == QueueStatus.pending
    assert await _fetch_status(unknown_row_id) == QueueStatus.running
