"""worker-reliability D4: GET /episodes/{episode_id} single-episode lookup.

Spec: episode-list-api → Requirement "Single-episode endpoint". The URL
deep-link receiver resolves episodes through this endpoint instead of
searching the paginated list, so episodes outside the newest page stay
reachable via shared links.
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus

from .conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no local Postgres"
)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded():
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Single Ep Test Show",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()
        ep = Episode(
            show_id=show.id,
            title="Single Ep",
            audio_url="https://example.com/a.mp3",
            guid=f"guid-single-{uuid.uuid4()}",
        )
        db.add(ep)
        await db.flush()
        tr = Transcript(episode_id=ep.id, status=TranscriptStatus.completed)
        db.add(tr)
        await db.commit()
        ids = {"show_id": show.id, "ep_id": ep.id, "tr_id": tr.id}

    yield ids

    async with AsyncSessionFactory() as db:
        await db.execute(delete(Transcript).where(Transcript.id == ids["tr_id"]))
        await db.execute(delete(Episode).where(Episode.id == ids["ep_id"]))
        await db.execute(delete(Show).where(Show.id == ids["show_id"]))
        await db.commit()


async def test_existing_episode_200_with_transcript_status(client, seeded):
    resp = await client.get(f"/episodes/{seeded['ep_id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(seeded["ep_id"])
    assert body["title"] == "Single Ep"
    assert body["transcript_status"] == "completed"


async def test_unknown_episode_404(client):
    resp = await client.get(f"/episodes/{uuid.uuid4()}")
    assert resp.status_code == 404
