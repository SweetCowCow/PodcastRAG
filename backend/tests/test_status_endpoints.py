import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus
from app.services import api_health


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def show_with_episodes():
    """Create a show with 4 episodes covering all status mixes; cleanup after."""
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Test Show",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()

        statuses = [
            TranscriptStatus.pending,
            TranscriptStatus.processing,
            TranscriptStatus.completed,
            TranscriptStatus.failed,
        ]
        ep_ids: list[uuid.UUID] = []
        for i, st in enumerate(statuses):
            ep = Episode(
                show_id=show.id,
                title=f"Ep {i}",
                audio_url=f"https://example.com/a/{i}.mp3",
                guid=f"guid-{show.id}-{i}",
            )
            db.add(ep)
            await db.flush()
            ep_ids.append(ep.id)
            tr = Transcript(
                episode_id=ep.id,
                status=st,
                error_message="quota exhausted: " + ("x" * 300) if st == TranscriptStatus.failed else None,
            )
            db.add(tr)
        await db.commit()
        show_id = show.id

    yield show_id

    async with AsyncSessionFactory() as db:
        await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


async def test_transcription_status_unknown_show_returns_404(client):
    fake_id = uuid.uuid4()
    resp = await client.get(f"/shows/{fake_id}/transcription-status")
    assert resp.status_code == 404
    assert "detail" in resp.json()


async def test_transcription_status_empty_show(client):
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Empty Show",
            rss_url=f"https://example.com/empty/{uuid.uuid4()}",
        )
        db.add(show)
        await db.commit()
        sid = show.id
    try:
        resp = await client.get(f"/shows/{sid}/transcription-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["counts"] == {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
        }
        assert body["currently_processing"] == []
        assert body["recent_failures"] == []
    finally:
        async with AsyncSessionFactory() as db:
            await db.execute(delete(Show).where(Show.id == sid))
            await db.commit()


async def test_transcription_status_mixed(client, show_with_episodes):
    resp = await client.get(
        f"/shows/{show_with_episodes}/transcription-status"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"] == {
        "pending": 1,
        "processing": 1,
        "completed": 1,
        "failed": 1,
    }
    assert len(body["currently_processing"]) == 1
    assert len(body["recent_failures"]) == 1
    failure = body["recent_failures"][0]
    # error_message truncated to 200 chars
    assert len(failure["error_message"]) == 200
    assert failure["error_category"] is None  # not stored on transcript yet


async def test_external_api_status_redis_down(client, monkeypatch, auth_admin):
    def _raise(*_a, **_kw):
        import redis as _r
        raise _r.ConnectionError("simulated")

    monkeypatch.setattr(
        api_health._get_redis(), "lrange", _raise
    )
    resp = await client.get(
        "/admin/external-api-status", cookies=auth_admin["cookies"]
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["apis"]) == 3
    for entry in body["apis"]:
        assert entry["latest"] is None
        assert entry["recent"] == []
        assert entry["degraded"] is True
