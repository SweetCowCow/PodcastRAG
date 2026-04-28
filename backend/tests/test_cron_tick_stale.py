"""Tests for cron_tick stale running detection sub-routine."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.cron_tick import _detect_stale_running, STALE_ERROR_MESSAGE


@pytest_asyncio.fixture
async def make_running_row():
    """Factory: create a queue row with status=running and given offset/celery_task_id."""
    created: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    async def _make(
        minutes_ago: int, celery_task_id: str | None
    ) -> tuple[str, str]:
        async with AsyncSessionFactory() as db:
            show = Show(
                title="Stale Test",
                rss_url=f"https://example.com/rss/{uuid.uuid4()}",
                language="zh-tw",
            )
            db.add(show)
            await db.flush()

            ep = Episode(
                show_id=show.id,
                episode_guid=str(uuid.uuid4()),
                title="Ep stale",
                audio_url="https://example.com/a.mp3",
            )
            db.add(ep)
            await db.flush()

            row = TranscriptionQueue(
                episode_id=ep.id,
                show_id=show.id,
                status=QueueStatus.running,
                position=900000 + len(created),
                whisper_model="whisper-1",
                started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
                celery_task_id=celery_task_id,
            )
            db.add(row)
            await db.commit()
            created.append((row.id, ep.id, show.id))
            return str(row.id), str(ep.id)

    yield _make

    async with AsyncSessionFactory() as db:
        for rid, eid, sid in created:
            await db.execute(delete(TranscriptionQueue).where(TranscriptionQueue.id == rid))
            await db.execute(delete(Episode).where(Episode.id == eid))
            await db.execute(delete(Show).where(Show.id == sid))
        await db.commit()


def _mock_inspect(active_ids: list[str], reserved_ids: list[str] | None = None) -> MagicMock:
    """Build a mock inspect() return value with given task IDs."""
    inspect = MagicMock()
    inspect.active.return_value = {"worker-1": [{"id": tid} for tid in active_ids]}
    inspect.reserved.return_value = {
        "worker-1": [{"id": tid} for tid in (reserved_ids or [])]
    }
    return inspect


async def _row_state(row_id: str):
    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        return row.status, row.error_message, row.celery_task_id, row.finished_at


@pytest.mark.asyncio
async def test_stale_with_task_id_not_active_marked_failed(make_running_row):
    row_id, _ = await make_running_row(minutes_ago=45, celery_task_id="abc-123")
    inspect = _mock_inspect(active_ids=["other-task"])
    with patch("app.workers.cron_tick.celery_app.control.inspect", return_value=inspect), \
         patch("app.workers.cron_tick.release_global_slot") as mock_release:
        marked = await _detect_stale_running(AsyncSessionFactory)
    assert marked == 1
    status, err, tid, finished = await _row_state(row_id)
    assert status == QueueStatus.failed
    assert err == STALE_ERROR_MESSAGE
    assert tid == "abc-123"
    assert finished is not None
    mock_release.assert_called_once_with("abc-123")


@pytest.mark.asyncio
async def test_stale_with_null_task_id_marked_failed_no_release(make_running_row):
    row_id, _ = await make_running_row(minutes_ago=35, celery_task_id=None)
    inspect = _mock_inspect(active_ids=["unrelated"])
    with patch("app.workers.cron_tick.celery_app.control.inspect", return_value=inspect), \
         patch("app.workers.cron_tick.release_global_slot") as mock_release:
        marked = await _detect_stale_running(AsyncSessionFactory)
    assert marked >= 1
    status, err, tid, _ = await _row_state(row_id)
    assert status == QueueStatus.failed
    assert err == STALE_ERROR_MESSAGE
    assert tid is None
    mock_release.assert_not_called()


@pytest.mark.asyncio
async def test_stale_with_task_id_in_active_preserved(make_running_row):
    row_id, _ = await make_running_row(minutes_ago=45, celery_task_id="xyz-789")
    inspect = _mock_inspect(active_ids=["xyz-789"])
    with patch("app.workers.cron_tick.celery_app.control.inspect", return_value=inspect), \
         patch("app.workers.cron_tick.release_global_slot") as mock_release:
        await _detect_stale_running(AsyncSessionFactory)
    status, err, _, _ = await _row_state(row_id)
    assert status == QueueStatus.running
    assert err is None
    mock_release.assert_not_called()


@pytest.mark.asyncio
async def test_running_younger_than_threshold_preserved(make_running_row):
    row_id, _ = await make_running_row(minutes_ago=10, celery_task_id=None)
    inspect = _mock_inspect(active_ids=["unrelated"])
    with patch("app.workers.cron_tick.celery_app.control.inspect", return_value=inspect), \
         patch("app.workers.cron_tick.release_global_slot"):
        await _detect_stale_running(AsyncSessionFactory)
    status, _, _, _ = await _row_state(row_id)
    assert status == QueueStatus.running


@pytest.mark.asyncio
async def test_inspect_empty_dicts_skips_detection(make_running_row):
    row_id, _ = await make_running_row(minutes_ago=45, celery_task_id="should-not-touch")
    inspect = MagicMock()
    inspect.active.return_value = {}
    inspect.reserved.return_value = {}
    with patch("app.workers.cron_tick.celery_app.control.inspect", return_value=inspect), \
         patch("app.workers.cron_tick.release_global_slot") as mock_release:
        marked = await _detect_stale_running(AsyncSessionFactory)
    assert marked == 0
    status, _, _, _ = await _row_state(row_id)
    assert status == QueueStatus.running
    mock_release.assert_not_called()


@pytest.mark.asyncio
async def test_inspect_raises_skips_detection(make_running_row):
    row_id, _ = await make_running_row(minutes_ago=45, celery_task_id="should-not-touch")
    inspect = MagicMock()
    inspect.active.side_effect = ConnectionError("broker down")
    with patch("app.workers.cron_tick.celery_app.control.inspect", return_value=inspect), \
         patch("app.workers.cron_tick.release_global_slot") as mock_release:
        marked = await _detect_stale_running(AsyncSessionFactory)
    assert marked == 0
    status, _, _, _ = await _row_state(row_id)
    assert status == QueueStatus.running
    mock_release.assert_not_called()
