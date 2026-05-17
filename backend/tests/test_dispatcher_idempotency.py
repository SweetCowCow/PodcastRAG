"""Tests for celery-routing-and-dispatcher-fix worker entry idempotency.

Covers Requirement: Worker task entry transitions queue row to running atomically
- Pending row claimed → status=running with this task_id (PROCEED)
- Duplicate within 5min skipped → row unchanged, decision=SKIP_DUPLICATE
- Stale beyond 5min reclaimed → started_at + task_id updated, decision=RECLAIMED
- Cancelled row acked → row unchanged, decision=SKIP_TERMINAL

Also covers Requirement: Dispatcher does not pre-mark row as running (3.1 / 3.2)
via direct exercise of dispatcher._try_pop_one.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.dispatcher import _try_pop_one
from app.workers.tasks import ClaimDecision, _claim_queue_row

from .conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="postgres not reachable"
)


@pytest_asyncio.fixture
async def queue_row_factory():
    created_ids: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    async def _make(
        *,
        status: QueueStatus = QueueStatus.pending,
        started_at: datetime | None = None,
        celery_task_id: str | None = None,
    ) -> tuple[str, str]:
        async with AsyncSessionFactory() as db:
            show = Show(
                title="Idempotency Test",
                rss_url=f"https://example.com/rss/{uuid.uuid4()}",
                language="zh-tw",
            )
            db.add(show)
            await db.flush()
            ep = Episode(
                show_id=show.id,
                guid=str(uuid.uuid4()),
                title="Ep",
                audio_url="https://example.com/a.mp3",
            )
            db.add(ep)
            await db.flush()
            row = TranscriptionQueue(
                episode_id=ep.id,
                show_id=show.id,
                status=status,
                position=999000 + len(created_ids),
                whisper_model="whisper-1",
                started_at=started_at,
                celery_task_id=celery_task_id,
            )
            db.add(row)
            await db.commit()
            created_ids.append((row.id, ep.id, show.id))
            return str(ep.id), str(row.id)

    yield _make

    async with AsyncSessionFactory() as db:
        for row_id, ep_id, show_id in created_ids:
            await db.execute(delete(TranscriptionQueue).where(TranscriptionQueue.id == row_id))
            await db.execute(delete(Episode).where(Episode.id == ep_id))
            await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


@pytest.mark.asyncio
async def test_pending_row_claimed_proceed(queue_row_factory):
    ep_id, row_id = await queue_row_factory(status=QueueStatus.pending)
    returned_row_id, decision = await _claim_queue_row(ep_id, "task-fresh-1")
    assert returned_row_id == row_id
    assert decision == ClaimDecision.PROCEED

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        assert row.status == QueueStatus.running
        assert row.celery_task_id == "task-fresh-1"
        assert row.started_at is not None


@pytest.mark.asyncio
async def test_duplicate_within_5min_skipped(queue_row_factory):
    started = datetime.now(timezone.utc) - timedelta(minutes=2)
    ep_id, row_id = await queue_row_factory(
        status=QueueStatus.running,
        started_at=started,
        celery_task_id="task-original",
    )
    returned_row_id, decision = await _claim_queue_row(ep_id, "task-duplicate")
    assert returned_row_id == row_id
    assert decision == ClaimDecision.SKIP_DUPLICATE

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        # Unchanged
        assert row.celery_task_id == "task-original"
        assert row.status == QueueStatus.running


@pytest.mark.asyncio
async def test_stale_beyond_5min_reclaimed(queue_row_factory):
    started = datetime.now(timezone.utc) - timedelta(minutes=12)
    ep_id, row_id = await queue_row_factory(
        status=QueueStatus.running,
        started_at=started,
        celery_task_id="task-ghost",
    )
    returned_row_id, decision = await _claim_queue_row(ep_id, "task-new")
    assert returned_row_id == row_id
    assert decision == ClaimDecision.RECLAIMED

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        assert row.celery_task_id == "task-new"
        # started_at refreshed
        assert row.started_at > started + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_running_with_null_started_at_treated_as_stale(queue_row_factory):
    """dispatcher cutover ghost row: status=running, started_at=NULL → reclaim safely."""
    ep_id, row_id = await queue_row_factory(
        status=QueueStatus.running, started_at=None, celery_task_id=None
    )
    returned_row_id, decision = await _claim_queue_row(ep_id, "task-recover")
    assert returned_row_id == row_id
    assert decision == ClaimDecision.RECLAIMED

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        assert row.celery_task_id == "task-recover"
        assert row.started_at is not None


@pytest.mark.asyncio
async def test_cancelled_row_acked(queue_row_factory):
    ep_id, row_id = await queue_row_factory(status=QueueStatus.cancelled)
    returned_row_id, decision = await _claim_queue_row(ep_id, "task-late")
    assert returned_row_id == row_id
    assert decision == ClaimDecision.SKIP_TERMINAL

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        assert row.status == QueueStatus.cancelled  # untouched
        # celery_task_id should NOT be overwritten for terminal rows.
        assert row.celery_task_id is None


@pytest.mark.asyncio
async def test_completed_row_acked(queue_row_factory):
    ep_id, row_id = await queue_row_factory(status=QueueStatus.completed)
    _returned_row_id, decision = await _claim_queue_row(ep_id, "task-very-late")
    assert decision == ClaimDecision.SKIP_TERMINAL


@pytest.mark.asyncio
async def test_no_row_returns_not_found():
    fake_episode = str(uuid.uuid4())
    returned_row_id, decision = await _claim_queue_row(fake_episode, "task-orphan")
    assert returned_row_id is None
    assert decision == ClaimDecision.NOT_FOUND


# ─── dispatcher behaviour: SHALL NOT pre-mark row as running ───


@pytest.mark.asyncio
async def test_dispatcher_does_not_mutate_row(queue_row_factory):
    """celery-routing-and-dispatcher-fix: dispatcher 改寫後只回傳 episode_id，
    不再 update row 的 status / started_at / celery_task_id。"""
    ep_id, row_id = await queue_row_factory(status=QueueStatus.pending)

    engine = create_async_engine(settings.database_url)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Maker() as session:
            popped = await _try_pop_one(session)
        assert popped == ep_id
    finally:
        await engine.dispose()

    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        # Row state unchanged after dispatcher sends task.
        assert row.status == QueueStatus.pending
        assert row.started_at is None
        assert row.celery_task_id is None
