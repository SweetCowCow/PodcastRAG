"""Integration: force-cancel a running row whose celery_task_id is NULL
SHALL still release the throttle slot keyed by row id.
"""
import socket
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.throttle import (
    GLOBAL_ACTIVE_KEY,
    GLOBAL_SLOT_KEY,
    _get_redis,
    acquire_global_slot,
)
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
async def client(auth_admin):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def running_row_null_task_id():
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Throttle Cancel Test",
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
            position=999800,
            whisper_model="whisper-1",
            celery_task_id=None,
        )
        db.add(row)
        await db.commit()
        ids = (str(row.id), episode.id, show.id)

    yield ids

    async with AsyncSessionFactory() as db:
        await db.execute(
            delete(TranscriptionQueue).where(
                TranscriptionQueue.id == uuid.UUID(ids[0])
            )
        )
        await db.execute(delete(Episode).where(Episode.id == ids[1]))
        await db.execute(delete(Show).where(Show.id == ids[2]))
        await db.commit()


@pytest.mark.asyncio
async def test_force_cancel_null_task_id_releases_slot(
    client, running_row_null_task_id
):
    queue_id, _, _ = running_row_null_task_id
    r = _get_redis()
    r.delete(GLOBAL_ACTIVE_KEY)
    r.delete(GLOBAL_SLOT_KEY.format(queue_id))

    assert acquire_global_slot(queue_id) is True
    assert int(r.get(GLOBAL_ACTIVE_KEY) or 0) == 1

    resp = await client.post(
        f"/admin/queue/{queue_id}/cancel", params={"force": "true"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["force_cancelled"] is True
    assert body["celery_task_id"] is None

    assert int(r.get(GLOBAL_ACTIVE_KEY) or 0) == 0
    assert r.get(GLOBAL_SLOT_KEY.format(queue_id)) is None
