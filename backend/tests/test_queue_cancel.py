"""Tests for POST /admin/queue/{id}/cancel covering normal + force paths."""
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcription_queue import QueueStatus, TranscriptionQueue


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
async def make_row():
    """Factory: create a queue row in a given status, return its id; cleanup after."""
    created: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    async def _make(
        row_status: QueueStatus, celery_task_id: str | None = None
    ) -> str:
        async with AsyncSessionFactory() as db:
            show = Show(
                title="Cancel API Test",
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
                status=row_status,
                position=999900 + len(created),
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


@pytest.mark.asyncio
async def test_cancel_pending_no_force_succeeds(client, make_row):
    queue_id = await make_row(QueueStatus.pending)
    resp = await client.post(f"/admin/queue/{queue_id}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["force_cancelled"] is False


@pytest.mark.asyncio
async def test_cancel_running_no_force_returns_409(client, make_row):
    queue_id = await make_row(QueueStatus.running, celery_task_id="task-aaa")
    resp = await client.post(f"/admin/queue/{queue_id}/cancel")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_force_cancel_running_with_task_id_revokes_and_updates(
    client, make_row
):
    queue_id = await make_row(QueueStatus.running, celery_task_id="task-bbb")
    with patch("app.api.queue.celery_app.control.revoke") as mock_revoke, patch(
        "app.api.queue.release_global_slot"
    ) as mock_release:
        resp = await client.post(
            f"/admin/queue/{queue_id}/cancel", params={"force": "true"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["force_cancelled"] is True
    assert body["celery_task_id"] == "task-bbb"
    assert body["error_message"] == "Force cancelled by admin"
    mock_revoke.assert_called_once_with(
        "task-bbb", terminate=True, signal="SIGTERM"
    )
    mock_release.assert_called_once_with(str(queue_id))


@pytest.mark.asyncio
async def test_force_cancel_running_with_null_task_id_skips_revoke(
    client, make_row
):
    queue_id = await make_row(QueueStatus.running, celery_task_id=None)
    with patch("app.api.queue.celery_app.control.revoke") as mock_revoke, patch(
        "app.api.queue.release_global_slot"
    ) as mock_release:
        resp = await client.post(
            f"/admin/queue/{queue_id}/cancel", params={"force": "true"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["force_cancelled"] is True
    assert body["celery_task_id"] is None
    mock_revoke.assert_not_called()
    mock_release.assert_called_once_with(str(queue_id))


@pytest.mark.asyncio
async def test_force_cancel_completed_returns_409(client, make_row):
    queue_id = await make_row(QueueStatus.completed)
    resp = await client.post(
        f"/admin/queue/{queue_id}/cancel", params={"force": "true"}
    )
    assert resp.status_code == 409
