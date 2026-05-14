"""Schema tests for R3.3 Phase 1: episodes.guests JSONB column + title_tsvector
nullable column with their GIN indexes.

Requires the dev database (`docker compose up -d db`).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_episode_guests_default_empty_list(db_session):
    """A newly inserted episode without explicit guests SHALL default to []."""
    from app.models.episode import Episode
    from app.models.show import Show

    show = Show(
        title=f"pytest-show-{uuid.uuid4().hex[:8]}",
        rss_url=f"https://example.com/{uuid.uuid4().hex[:8]}.xml",
    )
    db_session.add(show)
    await db_session.flush()

    ep = Episode(
        show_id=show.id,
        title="EP1 normal title without Ft.",
        audio_url="https://example.com/a.mp3",
        guid=f"pytest-ep-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(ep)
    await db_session.flush()
    await db_session.refresh(ep)

    assert ep.guests == []

    # Cleanup
    await db_session.delete(ep)
    await db_session.delete(show)
    await db_session.commit()


@pytest.mark.asyncio
async def test_episode_guests_jsonb_containment(db_session):
    """`guests @> '["馬世芳"]'::jsonb` SHALL find episodes whose list contains that guest."""
    from app.models.episode import Episode
    from app.models.show import Show

    show = Show(
        title=f"pytest-show-{uuid.uuid4().hex[:8]}",
        rss_url=f"https://example.com/{uuid.uuid4().hex[:8]}.xml",
    )
    db_session.add(show)
    await db_session.flush()

    ep_match = Episode(
        show_id=show.id,
        title="Ft. 馬世芳",
        audio_url="https://example.com/m.mp3",
        guid=f"pytest-ep-m-{uuid.uuid4().hex[:8]}",
        guests=["馬世芳"],
    )
    ep_other = Episode(
        show_id=show.id,
        title="Ft. 楊大正",
        audio_url="https://example.com/y.mp3",
        guid=f"pytest-ep-y-{uuid.uuid4().hex[:8]}",
        guests=["楊大正"],
    )
    db_session.add_all([ep_match, ep_other])
    await db_session.commit()

    rows = await db_session.execute(
        text(
            "SELECT id FROM episodes "
            "WHERE show_id = :sid AND guests @> CAST(:needle AS jsonb)"
        ),
        {"sid": show.id, "needle": '["馬世芳"]'},
    )
    found_ids = {r[0] for r in rows.all()}
    assert ep_match.id in found_ids
    assert ep_other.id not in found_ids

    await db_session.delete(ep_match)
    await db_session.delete(ep_other)
    await db_session.delete(show)
    await db_session.commit()


@pytest.mark.asyncio
async def test_episode_title_tsvector_column_writeable(db_session):
    """title_tsvector column accepts a tsvector value written from Python."""
    from sqlalchemy import func

    from app.models.episode import Episode
    from app.models.show import Show

    show = Show(
        title=f"pytest-show-{uuid.uuid4().hex[:8]}",
        rss_url=f"https://example.com/{uuid.uuid4().hex[:8]}.xml",
    )
    db_session.add(show)
    await db_session.flush()

    ep = Episode(
        show_id=show.id,
        title="EP100 高雄美食",
        audio_url="https://example.com/t.mp3",
        guid=f"pytest-ep-t-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(ep)
    await db_session.flush()

    # Write via raw to_tsvector to mirror what Phase 2/3 indexer will do.
    await db_session.execute(
        text(
            "UPDATE episodes SET title_tsvector = to_tsvector('simple', :tokens) "
            "WHERE id = :id"
        ),
        {"tokens": "ep100 高雄 美食", "id": ep.id},
    )
    await db_session.commit()
    await db_session.refresh(ep)

    assert ep.title_tsvector is not None
    assert "高雄" in str(ep.title_tsvector) or "高雄" in ep.title_tsvector  # type: ignore[operator]

    await db_session.delete(ep)
    await db_session.delete(show)
    await db_session.commit()
