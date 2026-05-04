"""Tests for cron_tick._detect_stale_summary_running.

Build episode rows in various stale/fresh states and verify the helper
resets stale rows + re-enqueues, while leaving fresh rows alone.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.models.episode import AiSummaryStatus, Episode
from app.models.show import Show
from app.workers.cron_tick import _detect_stale_summary_running

from .conftest import _postgres_reachable


async def _make_episode(
    db, *, status: str, started_offset_seconds: int | None
) -> uuid.UUID:
    show = Show(
        title="Stale Summary Test",
        rss_url=f"https://example.com/rss/{uuid.uuid4()}",
        language="zh-tw",
    )
    db.add(show)
    await db.flush()
    ep = Episode(
        show_id=show.id,
        title="Stale Summary Episode",
        audio_url="https://example.com/a.mp3",
        guid=f"guid-{uuid.uuid4()}",
        ai_summary_status=status,
        ai_summary_started_at=(
            datetime.now(timezone.utc)
            - timedelta(seconds=started_offset_seconds)
            if started_offset_seconds is not None
            else None
        ),
    )
    db.add(ep)
    await db.commit()
    return ep.id


@pytest_asyncio.fixture
async def cleanup_test_shows():
    yield
    async with AsyncSessionFactory() as db:
        await db.execute(
            delete(Show).where(Show.title.like("Stale Summary%"))
        )
        await db.commit()


def _session_factory():
    return async_sessionmaker(
        create_async_engine(settings.database_url), expire_on_commit=False
    )


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_stale_row_reset_and_enqueued(cleanup_test_shows):
    async with AsyncSessionFactory() as db:
        ep_id = await _make_episode(
            db,
            status=AiSummaryStatus.running.value,
            started_offset_seconds=settings.summary_stale_threshold_seconds + 100,
        )

    with patch(
        "app.workers.cron_tick.generate_episode_summary"
    ) as mock_task:
        mock_task.delay = MagicMock()
        recovered = await _detect_stale_summary_running(_session_factory())

    assert recovered == 1
    mock_task.delay.assert_called_once_with(str(ep_id))
    async with AsyncSessionFactory() as db:
        ep = await db.get(Episode, ep_id)
        assert ep.ai_summary_status == AiSummaryStatus.pending.value
        assert ep.ai_summary_started_at is None
        assert ep.ai_summary_error is not None
        assert ep.ai_summary_error.startswith("recovered from stale running after")


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_fresh_running_row_left_alone(cleanup_test_shows):
    async with AsyncSessionFactory() as db:
        ep_id = await _make_episode(
            db,
            status=AiSummaryStatus.running.value,
            started_offset_seconds=60,  # well within threshold
        )

    with patch(
        "app.workers.cron_tick.generate_episode_summary"
    ) as mock_task:
        mock_task.delay = MagicMock()
        recovered = await _detect_stale_summary_running(_session_factory())

    assert recovered == 0
    mock_task.delay.assert_not_called()
    async with AsyncSessionFactory() as db:
        ep = await db.get(Episode, ep_id)
        assert ep.ai_summary_status == AiSummaryStatus.running.value
        assert ep.ai_summary_started_at is not None


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_running_with_null_started_at_skipped(cleanup_test_shows, caplog):
    async with AsyncSessionFactory() as db:
        ep_id = await _make_episode(
            db,
            status=AiSummaryStatus.running.value,
            started_offset_seconds=None,
        )

    with patch(
        "app.workers.cron_tick.generate_episode_summary"
    ) as mock_task:
        mock_task.delay = MagicMock()
        with caplog.at_level("WARNING"):
            recovered = await _detect_stale_summary_running(_session_factory())

    assert recovered == 0
    mock_task.delay.assert_not_called()
    async with AsyncSessionFactory() as db:
        ep = await db.get(Episode, ep_id)
        assert ep.ai_summary_status == AiSummaryStatus.running.value
        assert ep.ai_summary_started_at is None
    assert any(
        "started_at IS NULL" in rec.message for rec in caplog.records
    )


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_per_row_enqueue_failure_rolls_back(cleanup_test_shows):
    """3 stale rows; first .delay() raises; that one rolls back to running,
    the other two reset + enqueue successfully → recovered=2."""
    ep_ids = []
    async with AsyncSessionFactory() as db:
        for offset in (700, 800, 900):
            ep_ids.append(
                await _make_episode(
                    db,
                    status=AiSummaryStatus.running.value,
                    started_offset_seconds=offset,
                )
            )

    call_log = []

    def fake_delay(arg):
        call_log.append(arg)
        if len(call_log) == 1:
            raise RuntimeError("broker boom")

    with patch(
        "app.workers.cron_tick.generate_episode_summary"
    ) as mock_task:
        mock_task.delay = MagicMock(side_effect=fake_delay)
        recovered = await _detect_stale_summary_running(_session_factory())

    assert recovered == 2
    assert len(call_log) == 3

    # Determine which row was the first processed (rolled back) vs the rest.
    failed_id = uuid.UUID(call_log[0])
    succeeded_ids = {uuid.UUID(x) for x in call_log[1:]}

    async with AsyncSessionFactory() as db:
        rolled = await db.get(Episode, failed_id)
        assert rolled.ai_summary_status == AiSummaryStatus.running.value
        assert rolled.ai_summary_started_at is not None
        for sid in succeeded_ids:
            ep = await db.get(Episode, sid)
            assert ep.ai_summary_status == AiSummaryStatus.pending.value
            assert ep.ai_summary_started_at is None
            assert ep.ai_summary_error.startswith(
                "recovered from stale running after"
            )
