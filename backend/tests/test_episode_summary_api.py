"""Verify GET /shows/{id}/episodes exposes ai_summary fields and hides
admin-only ai_summary_model.
"""
import uuid
from datetime import datetime, timezone

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import AiSummaryStatus, Episode
from app.models.show import Show

from .conftest import _postgres_reachable


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def show_with_summary_states():
    """Three episodes covering done / pending / failed summary states."""
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Summary Test Show",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()

        states = [
            (AiSummaryStatus.done, "this is the AI summary text", "gpt-5-mini"),
            (AiSummaryStatus.pending, None, None),
            (AiSummaryStatus.failed, None, "gpt-5-mini"),
        ]
        for i, (st, summary, model) in enumerate(states):
            ep = Episode(
                show_id=show.id,
                title=f"Ep {i}",
                audio_url=f"https://example.com/a/{i}.mp3",
                guid=f"guid-{show.id}-{i}",
                ai_summary=summary,
                ai_summary_status=st.value,
                ai_summary_generated_at=datetime.now(timezone.utc) if model else None,
                ai_summary_model=model,
            )
            db.add(ep)
        await db.commit()
        show_id = show.id

    yield show_id

    async with AsyncSessionFactory() as db:
        await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


import pytest


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_episode_list_exposes_ai_summary_fields_and_hides_model(
    client, show_with_summary_states
):
    resp = await client.get(f"/shows/{show_with_summary_states}/episodes")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 3
    statuses = sorted(it["ai_summary_status"] for it in items)
    assert statuses == ["done", "failed", "pending"]

    done = next(it for it in items if it["ai_summary_status"] == "done")
    assert done["ai_summary"] == "this is the AI summary text"
    pending = next(it for it in items if it["ai_summary_status"] == "pending")
    assert pending["ai_summary"] is None

    # Admin-only field MUST NOT leak through public list endpoint.
    for it in items:
        assert "ai_summary_model" not in it
        assert "ai_summary_generated_at" not in it
