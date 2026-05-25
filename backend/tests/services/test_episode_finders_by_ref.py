"""Regression tests for `find_by_ref` SQL — prevents the SQLAlchemy
bind-parameter collision bug that broke all `find_episode_by_ref`
calls in prod 2026-05-25.

Spec: chat-agentic-routing → Requirement
"Episode reference resolver SQL SHALL NOT collide with SQLAlchemy bind syntax"
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app.services import episode_finders
from tests.conftest import _postgres_reachable


def test_sql_string_has_no_pcre_non_capturing_group():
    """Static regression: the SQL string MUST NOT contain `(?:` —
    SQLAlchemy parses `:EP` / `:集` inside `(?:EP|第)` / `(?:集)?` as
    bind-parameter markers, raising StatementError at execute time."""
    sql = episode_finders._BY_REF_EP_NUMBER_SQL
    assert "(?:" not in sql, (
        "find_by_ref EP-number SQL must not use PCRE non-capturing groups; "
        "SQLAlchemy treats `:EP` / `:集` as bind params and raises at execute"
    )


# ─── Real-PG tests (skip when no local PG) ─────────────────────────────


@pytest_asyncio.fixture
async def episode_fixture(db_session):
    """Seed a temporary show + 2 episodes (EP19, EP143) for find_by_ref
    integration tests. Cleans up via the `pytest-finder` title prefix."""
    from app.models.episode import Episode
    from app.models.show import Show
    from sqlalchemy import delete

    suffix = uuid.uuid4().hex[:6]
    title_prefix = f"pytest-finder-{suffix}"

    show = Show(
        title=f"{title_prefix} test show",
        rss_url=f"https://example.com/{suffix}.rss",
    )
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    ep19 = Episode(
        show_id=show.id,
        guid=f"{title_prefix}-ep19",
        title=f"EP19｜{title_prefix} 動漫歌單",
        audio_url=f"https://example.com/{title_prefix}-ep19.mp3",
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    ep143 = Episode(
        show_id=show.id,
        guid=f"{title_prefix}-ep143",
        title=f"EP143｜{title_prefix} 家常味",
        audio_url=f"https://example.com/{title_prefix}-ep143.mp3",
        published_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    db_session.add_all([ep19, ep143])
    await db_session.commit()
    await db_session.refresh(ep19)
    await db_session.refresh(ep143)

    yield {"show": show, "ep19": ep19, "ep143": ep143, "title_prefix": title_prefix}

    await db_session.execute(delete(Episode).where(Episode.show_id == show.id))
    await db_session.execute(delete(Show).where(Show.id == show.id))
    await db_session.commit()


@pytest.mark.skipif(not _postgres_reachable(), reason="needs local PG")
@pytest.mark.asyncio
async def test_find_by_ref_resolves_ep_number(db_session, episode_fixture):
    """(a) `find_by_ref(ref='EP143')` resolves to the EP143 fixture row
    without raising StatementError."""
    ref = await episode_finders.find_by_ref(
        db_session, episode_fixture["show"].id, "EP143"
    )
    assert ref is not None, "find_by_ref returned None for EP143"
    assert ref.episode_id == episode_fixture["ep143"].id


@pytest.mark.skipif(not _postgres_reachable(), reason="needs local PG")
@pytest.mark.asyncio
async def test_find_by_ref_resolves_chinese_ordinal(db_session, episode_fixture):
    """(b) `find_by_ref(ref='第19集')` resolves to the same row as `EP19`
    via the shared regex branch."""
    ref = await episode_finders.find_by_ref(
        db_session, episode_fixture["show"].id, "第19集"
    )
    assert ref is not None, "find_by_ref returned None for 第19集"
    assert ref.episode_id == episode_fixture["ep19"].id

    ref_ep_form = await episode_finders.find_by_ref(
        db_session, episode_fixture["show"].id, "EP19"
    )
    assert ref_ep_form is not None
    assert ref_ep_form.episode_id == ref.episode_id


@pytest.mark.skipif(not _postgres_reachable(), reason="needs local PG")
@pytest.mark.asyncio
async def test_find_by_ref_returns_none_for_unknown(db_session, episode_fixture):
    """(c) `find_by_ref(ref='EP999')` returns None when no episode title
    contains EP999 and no title-ILIKE fallback match exists."""
    ref = await episode_finders.find_by_ref(
        db_session, episode_fixture["show"].id, "EP999"
    )
    assert ref is None
