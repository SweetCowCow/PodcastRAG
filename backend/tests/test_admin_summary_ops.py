"""Admin summary regenerate + backfill endpoints."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import AiSummaryStatus, Episode
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus

from .conftest import _postgres_reachable, csrf_headers


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def show_with_episodes_summary_mix():
    """Show with 4 episodes: 2 transcribed-no-summary, 1 done, 1 not-transcribed."""
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Backfill Test",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()

        episodes_spec = [
            (TranscriptStatus.completed, AiSummaryStatus.pending, None),
            (TranscriptStatus.completed, AiSummaryStatus.failed, None),
            (TranscriptStatus.completed, AiSummaryStatus.done, "已有摘要"),
            (TranscriptStatus.pending, AiSummaryStatus.pending, None),
        ]
        ep_ids = []
        for i, (ts, ss, summary) in enumerate(episodes_spec):
            ep = Episode(
                show_id=show.id,
                title=f"Ep {i}",
                audio_url=f"https://example.com/a/{i}.mp3",
                guid=f"guid-{show.id}-{i}",
                ai_summary=summary,
                ai_summary_status=ss.value,
            )
            db.add(ep)
            await db.flush()
            ep_ids.append(ep.id)
            tr = Transcript(episode_id=ep.id, status=ts)
            db.add(tr)
        await db.commit()
        show_id = show.id

    yield show_id, ep_ids

    async with AsyncSessionFactory() as db:
        await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


# ─── Auth tests ────────────────────────────────────────────────────────


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_regenerate_unauthenticated_rejected(client):
    """No session + no CSRF/Origin → CSRF middleware rejects with 403 before
    auth dependency runs. Either 401 or 403 is acceptable as long as the
    request never reaches the handler."""
    r = await client.post(
        f"/admin/episodes/{uuid.uuid4()}/regenerate-summary"
    )
    assert r.status_code in (401, 403)


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_regenerate_member_403(client, auth_member):
    r = await client.post(
        f"/admin/episodes/{uuid.uuid4()}/regenerate-summary",
        cookies=auth_member["cookies"],
        headers=csrf_headers(auth_member["session_token"]),
    )
    assert r.status_code == 403


# ─── Regenerate ────────────────────────────────────────────────────────


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_regenerate_404_on_missing_episode(client, auth_admin):
    r = await client.post(
        f"/admin/episodes/{uuid.uuid4()}/regenerate-summary",
        cookies=auth_admin["cookies"],
        headers=csrf_headers(auth_admin["session_token"]),
    )
    assert r.status_code == 404


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_regenerate_resets_status_and_enqueues(
    client, auth_admin, show_with_episodes_summary_mix
):
    _, ep_ids = show_with_episodes_summary_mix
    target = ep_ids[2]  # the 'done' one

    with patch(
        "app.workers.summary_task.generate_episode_summary.delay"
    ) as mock_delay:
        r = await client.post(
            f"/admin/episodes/{target}/regenerate-summary",
            cookies=auth_admin["cookies"],
            headers=csrf_headers(auth_admin["session_token"]),
        )
    assert r.status_code == 200
    assert r.json() == {"episode_id": str(target), "enqueued": True}
    mock_delay.assert_called_once_with(str(target))

    # DB row reset to pending.
    async with AsyncSessionFactory() as db:
        ep = await db.get(Episode, target)
        assert ep.ai_summary_status == "pending"


# ─── Backfill ──────────────────────────────────────────────────────────


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_backfill_counts_only_eligible_rows(
    client, auth_admin, show_with_episodes_summary_mix
):
    """Eligible = transcript completed AND ai_summary IS NULL.

    Fixture: 2 rows match (pending + failed both have ai_summary=None and
    transcript=completed). 1 row has summary set (done) → excluded. 1 row's
    transcript is pending → excluded.
    """
    with patch(
        "app.workers.summary_task.generate_episode_summary.delay"
    ) as mock_delay:
        r = await client.post(
            "/admin/episodes/backfill-summary",
            cookies=auth_admin["cookies"],
            headers=csrf_headers(auth_admin["session_token"]),
        )
    assert r.status_code == 200
    body = r.json()
    # Account for other shows in dev DB that might also match. Assert at
    # least 2 from our fixture got enqueued.
    assert body["enqueued_count"] >= 2
    assert mock_delay.call_count == body["enqueued_count"]


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_backfill_idempotent_after_summaries_set(
    client, auth_admin, show_with_episodes_summary_mix
):
    """Once we mark all eligible rows as having a summary, a second backfill
    enqueues 0 from the fixture (other dev rows may still bump the count,
    but our 2 fixture rows must no longer contribute)."""
    show_id, ep_ids = show_with_episodes_summary_mix

    # Manually fill summaries on the 2 eligible rows.
    async with AsyncSessionFactory() as db:
        for ep_id in (ep_ids[0], ep_ids[1]):
            ep = await db.get(Episode, ep_id)
            ep.ai_summary = "filled"
            ep.ai_summary_status = "done"
        await db.commit()

    with patch(
        "app.workers.summary_task.generate_episode_summary.delay"
    ) as mock_delay:
        r = await client.post(
            "/admin/episodes/backfill-summary",
            cookies=auth_admin["cookies"],
            headers=csrf_headers(auth_admin["session_token"]),
        )
    assert r.status_code == 200
    # Confirm none of OUR fixture's eligible rows got re-enqueued.
    enqueued_ids = {call.args[0] for call in mock_delay.call_args_list}
    assert str(ep_ids[0]) not in enqueued_ids
    assert str(ep_ids[1]) not in enqueued_ids
