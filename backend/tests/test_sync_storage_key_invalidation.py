"""transcription-pipeline-resilience B1: RSS re-sync invalidates the stored
audio object when an episode's audio_url changes.

Spec: rss-feed → Requirement "Sync show episodes endpoint" (modified).
Drives `sync_show_episodes` with a mocked `fetch_and_parse` against the real
local Postgres and asserts:

1. changed audio_url → `audio_storage_key` becomes NULL (episode counted as
   updated), so the next transcription re-downloads from the new URL.
2. unchanged audio_url (only title changed) → `audio_storage_key` untouched.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete

from tests.conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no local Postgres"
)


def _feed(guid: str, *, title: str, audio_url: str):
    ep = SimpleNamespace(
        guid=guid,
        title=title,
        description="desc",
        audio_url=audio_url,
        duration_seconds=100,
        published_at=None,
        guests=None,
    )
    return SimpleNamespace(episodes=[ep])


@pytest_asyncio.fixture
async def seeded(db_session):
    from app.models.episode import Episode
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    show = Show(
        title=f"pytest-syncb1-{suffix}",
        rss_url=f"https://e.com/{suffix}.rss",
        language="zh",
    )
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    guid = f"pytest-syncb1-{suffix}-ep"
    ep = Episode(
        show_id=show.id,
        guid=guid,
        title="原標題",
        description="desc",
        audio_url="https://e.com/old.mp3",
        duration_seconds=100,
        audio_storage_key=f"audio/{suffix}-old.mp3",
    )
    db_session.add(ep)
    await db_session.commit()
    await db_session.refresh(ep)

    yield {"show_id": show.id, "ep_id": ep.id, "guid": guid}

    from app.models.episode import Episode as Ep
    from app.models.show import Show as Sh

    await db_session.execute(delete(Ep).where(Ep.show_id == show.id))
    await db_session.execute(delete(Sh).where(Sh.id == show.id))
    await db_session.commit()


async def _reload(db_session, ep_id):
    from app.models.episode import Episode

    ep = await db_session.get(Episode, ep_id)
    await db_session.refresh(ep)
    return ep


async def test_changed_audio_url_invalidates_storage_key(
    db_session, seeded, monkeypatch
):
    from app.services import sync

    monkeypatch.setattr(
        sync,
        "fetch_and_parse",
        AsyncMock(
            return_value=_feed(
                seeded["guid"], title="原標題", audio_url="https://e.com/new.mp3"
            )
        ),
    )
    result = await sync.sync_show_episodes(seeded["show_id"], db_session)
    await db_session.commit()

    assert result["updated"] == 1
    ep = await _reload(db_session, seeded["ep_id"])
    assert ep.audio_url == "https://e.com/new.mp3"
    assert ep.audio_storage_key is None


async def test_unchanged_audio_url_keeps_storage_key(
    db_session, seeded, monkeypatch
):
    from app.services import sync

    monkeypatch.setattr(
        sync,
        "fetch_and_parse",
        AsyncMock(
            return_value=_feed(
                seeded["guid"], title="新標題", audio_url="https://e.com/old.mp3"
            )
        ),
    )
    result = await sync.sync_show_episodes(seeded["show_id"], db_session)
    await db_session.commit()

    assert result["updated"] == 1
    ep = await _reload(db_session, seeded["ep_id"])
    assert ep.title == "新標題"
    assert ep.audio_storage_key is not None
    assert ep.audio_storage_key.endswith("-old.mp3")
