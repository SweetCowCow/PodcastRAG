"""Smoke test for R3.3 Phase 3 backfill_guests script.

Inserts a handful of fixture episodes with mixed Ft./Feat. patterns, runs
the backfill against the local DB, verifies guests are written correctly,
then runs it again to confirm idempotency (no further changes).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


_FIXTURES = [
    ("EP fixture A normal", []),
    ("EP fixture B Ft. 阿廣", ["阿廣"]),
    ("EP fixture C 【Ft. 楊大正 / 張凱婷】", ["楊大正", "張凱婷"]),
    ("EP fixture D feat. TMEX", ["TMEX"]),
    ("EP fixture E featuring 馬世芳", ["馬世芳"]),
]


@pytest.mark.asyncio
async def test_backfill_guests_writes_then_idempotent(db_session):
    from app.models.episode import Episode
    from app.models.show import Show
    from scripts.backfill_guests import _run

    show = Show(
        title=f"pytest-bg-{uuid.uuid4().hex[:8]}",
        rss_url=f"https://example.com/{uuid.uuid4().hex[:8]}.xml",
    )
    db_session.add(show)
    await db_session.flush()

    fixture_ids: list[uuid.UUID] = []
    for title, _expected in _FIXTURES:
        ep = Episode(
            show_id=show.id,
            title=title,
            audio_url=f"https://example.com/{uuid.uuid4().hex[:8]}.mp3",
            guid=f"pytest-{uuid.uuid4().hex[:12]}",
        )
        db_session.add(ep)
        await db_session.flush()
        fixture_ids.append(ep.id)
    await db_session.commit()

    # First backfill — populates guests.
    class _Args:
        all = False
        show_id = str(show.id)
        episode_id = None
        dry_run = False
        progress_every = 100

    await _run(_Args())

    rows = (await db_session.execute(
        select(Episode).where(Episode.id.in_(fixture_ids))
    )).scalars().all()
    by_title = {ep.title: ep for ep in rows}
    for title, expected in _FIXTURES:
        ep = by_title[title]
        await db_session.refresh(ep)
        assert ep.guests == expected, f"{title!r}: expected {expected}, got {ep.guests}"

    # Second run — every row unchanged.
    await _run(_Args())
    for title, expected in _FIXTURES:
        ep = by_title[title]
        await db_session.refresh(ep)
        assert ep.guests == expected, f"idempotency: {title!r} drifted to {ep.guests}"

    # Cleanup
    for ep_id in fixture_ids:
        ep = await db_session.get(Episode, ep_id)
        if ep is not None:
            await db_session.delete(ep)
    await db_session.delete(show)
    await db_session.commit()


@pytest.mark.asyncio
async def test_backfill_guests_dry_run_writes_nothing(db_session):
    from app.models.episode import Episode
    from app.models.show import Show
    from scripts.backfill_guests import _run

    show = Show(
        title=f"pytest-bg-{uuid.uuid4().hex[:8]}",
        rss_url=f"https://example.com/{uuid.uuid4().hex[:8]}.xml",
    )
    db_session.add(show)
    await db_session.flush()

    ep = Episode(
        show_id=show.id,
        title="EP fixture Ft. 阿廣",
        audio_url=f"https://example.com/{uuid.uuid4().hex[:8]}.mp3",
        guid=f"pytest-{uuid.uuid4().hex[:12]}",
    )
    db_session.add(ep)
    await db_session.flush()
    ep_id = ep.id
    await db_session.commit()

    class _Args:
        all = False
        show_id = str(show.id)
        episode_id = None
        dry_run = True
        progress_every = 100

    await _run(_Args())
    refreshed = await db_session.get(Episode, ep_id)
    await db_session.refresh(refreshed)
    # Default still [] because dry-run didn't commit
    assert refreshed.guests == []

    await db_session.delete(refreshed)
    await db_session.delete(show)
    await db_session.commit()
