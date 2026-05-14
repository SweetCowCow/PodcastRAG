"""Tests for the R3.3 Phase 4 admin Episode Guests endpoints."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import Episode
from app.models.show import Show

from .conftest import csrf_headers


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def show_with_episodes():
    """Seed a show with 3 episodes (descending dates), then clean up."""
    async with AsyncSessionFactory() as db:
        show = Show(
            title=f"Guests-Test {uuid.uuid4().hex[:6]}",
            rss_url=f"https://example.com/{uuid.uuid4().hex[:8]}.xml",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()
        ep_ids = []
        from datetime import datetime, timezone, timedelta
        base = datetime(2026, 5, 1, tzinfo=timezone.utc)
        for i, title in enumerate(
            ["EP1 Ft. 甲", "EP2 Feat. 乙、丙", "EP3 normal title"]
        ):
            ep = Episode(
                show_id=show.id,
                title=title,
                audio_url=f"https://example.com/{i}.mp3",
                guid=f"pytest-{uuid.uuid4().hex[:12]}",
                published_at=base + timedelta(days=i),
            )
            db.add(ep)
            await db.flush()
            ep_ids.append(ep.id)
        await db.commit()

    yield {"show_id": show.id, "episode_ids": ep_ids}

    async with AsyncSessionFactory() as db:
        for ep_id in ep_ids:
            ep = await db.get(Episode, ep_id)
            if ep is not None:
                await db.delete(ep)
        s = await db.get(Show, show.id)
        if s is not None:
            await db.delete(s)
        await db.commit()


@pytest.mark.asyncio
async def test_get_episode_guests_returns_snapshot(client, auth_admin, show_with_episodes):
    ep_id = show_with_episodes["episode_ids"][0]
    r = await client.get(
        f"/admin/episodes/{ep_id}/guests",
        cookies=auth_admin["cookies"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["episode_id"] == str(ep_id)
    assert body["title"] == "EP1 Ft. 甲"
    assert body["guests"] == []  # backfill not run in this test


@pytest.mark.asyncio
async def test_put_episode_guests_replaces_list(client, auth_admin, show_with_episodes):
    ep_id = show_with_episodes["episode_ids"][0]
    r = await client.put(
        f"/admin/episodes/{ep_id}/guests",
        json={"guests": ["馬世芳", "Leo王"]},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["guests"] == ["馬世芳", "Leo王"]

    # Verify DB really took it
    async with AsyncSessionFactory() as db:
        ep = await db.get(Episode, ep_id)
        assert ep.guests == ["馬世芳", "Leo王"]


@pytest.mark.asyncio
async def test_put_episode_guests_strips_whitespace_and_rejects_empty(
    client, auth_admin, show_with_episodes
):
    ep_id = show_with_episodes["episode_ids"][0]

    # Whitespace gets stripped
    r = await client.put(
        f"/admin/episodes/{ep_id}/guests",
        json={"guests": ["  馬世芳  ", "Leo王 "]},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200
    assert r.json()["guests"] == ["馬世芳", "Leo王"]

    # Empty string rejected
    r = await client.put(
        f"/admin/episodes/{ep_id}/guests",
        json={"guests": ["   "]},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_episode_guests_404_for_unknown_episode(client, auth_admin):
    fake = uuid.uuid4()
    r = await client.put(
        f"/admin/episodes/{fake}/guests",
        json={"guests": []},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_gets_403(client, auth_member, show_with_episodes):
    ep_id = show_with_episodes["episode_ids"][0]
    r = await client.get(
        f"/admin/episodes/{ep_id}/guests",
        cookies=auth_member["cookies"],
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_show_episodes_sorted_newest_first(client, auth_admin, show_with_episodes):
    show_id = show_with_episodes["show_id"]
    r = await client.get(
        f"/admin/shows/{show_id}/guests",
        cookies=auth_admin["cookies"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 3
    # Sorted newest first → EP3 (day 3) → EP2 → EP1
    titles = [ep["title"] for ep in body]
    assert titles == ["EP3 normal title", "EP2 Feat. 乙、丙", "EP1 Ft. 甲"]


@pytest.mark.asyncio
async def test_list_show_episodes_404_for_unknown_show(client, auth_admin):
    fake = uuid.uuid4()
    r = await client.get(
        f"/admin/shows/{fake}/guests",
        cookies=auth_admin["cookies"],
    )
    assert r.status_code == 404
