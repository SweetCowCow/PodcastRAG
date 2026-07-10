"""celery-routing-and-dispatcher-fix:

- Dispatcher self-race fix (`dispatched_at` column + SKIP LOCKED)
- Worker entry idempotency (`_claim_queue_row` 4 scenarios)
- Startup hook 模稜兩可 + stuck dispatched_at reset

需要本地 Postgres（不需 Redis；throttle 路徑不在這些 case 內被觸發）。
"""
from __future__ import annotations

import socket
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.dispatcher import _try_pop_one
from app.workers.lifecycle import _reset_ambiguous_and_stuck_rows_async
from app.workers.tasks import (
    CLAIM_NOT_FOUND,
    CLAIM_PROCEED,
    CLAIM_SKIP_DUPLICATE,
    CLAIM_SKIP_TERMINAL,
    _claim_queue_row,
)
from tests.conftest import _postgres_reachable


def _redis_reachable() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", 6379))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _db_connectable() -> bool:
    """settings.database_url 真的可以連得到 PG（不只 socket reachable）。"""
    if not _postgres_reachable():
        return False
    try:
        import asyncio

        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        async def _check():
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.connect():
                    return True
            finally:
                await engine.dispose()

        return asyncio.run(_check())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_connectable(),
    reason="local postgres + valid DATABASE_URL credentials required "
    "(run `docker compose -f backend/docker-compose.yml up -d db` first)",
)


@pytest_asyncio.fixture
async def make_row():
    """Factory: 建一個 (show, episode, queue_row) 三件套，回 queue_row_id。
    可指定 status / started_at / dispatched_at / ignored / celery_task_id。"""
    created: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    async def _make(
        *,
        status: QueueStatus = QueueStatus.pending,
        started_at: datetime | None = None,
        dispatched_at: datetime | None = None,
        ignored: bool = False,
        celery_task_id: str | None = None,
        position: int | None = None,
        whisper_model: str = "whisper-1",
    ) -> tuple[str, str]:
        async with AsyncSessionFactory() as db:
            show = Show(
                title="Idem Test",
                rss_url=f"https://example.com/rss/{uuid.uuid4()}",
                language="zh-tw",
            )
            db.add(show)
            await db.flush()
            episode = Episode(
                show_id=show.id,
                guid=str(uuid.uuid4()),
                title="Ep",
                audio_url="https://example.com/a.mp3",
            )
            db.add(episode)
            await db.flush()
            row = TranscriptionQueue(
                episode_id=episode.id,
                show_id=show.id,
                status=status,
                position=position if position is not None else 990000 + len(created),
                whisper_model=whisper_model,
                celery_task_id=celery_task_id,
                started_at=started_at,
                dispatched_at=dispatched_at,
                ignored=ignored,
            )
            db.add(row)
            await db.commit()
            created.append((row.id, episode.id, show.id))
            return str(row.id), str(episode.id)

    yield _make

    async with AsyncSessionFactory() as db:
        for row_id, ep_id, show_id in created:
            await db.execute(
                delete(TranscriptionQueue).where(TranscriptionQueue.id == row_id)
            )
            await db.execute(delete(Episode).where(Episode.id == ep_id))
            await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


async def _get(row_id: str) -> TranscriptionQueue:
    async with AsyncSessionFactory() as db:
        return await db.get(TranscriptionQueue, uuid.UUID(row_id))


# ─── Worker entry idempotency (task 4.1, 4 scenarios) ───


@pytest.mark.asyncio
async def test_pending_row_claimed_and_processed(make_row):
    row_id, ep_id = await make_row(status=QueueStatus.pending)
    claim, returned = await _claim_queue_row(ep_id, "task-1")
    assert claim == CLAIM_PROCEED
    assert returned == row_id

    row = await _get(row_id)
    assert row.status == QueueStatus.running
    assert row.celery_task_id == "task-1"
    assert row.started_at is not None
    assert row.dispatched_at is None


@pytest.mark.asyncio
async def test_duplicate_within_5min_acked_and_skipped(make_row):
    started = datetime.now(timezone.utc) - timedelta(minutes=2)
    row_id, ep_id = await make_row(
        status=QueueStatus.running,
        started_at=started,
        celery_task_id="task-orig",
    )
    claim, returned = await _claim_queue_row(ep_id, "task-dup")
    assert claim == CLAIM_SKIP_DUPLICATE
    assert returned == row_id

    row = await _get(row_id)
    # 不能被覆寫
    assert row.celery_task_id == "task-orig"
    assert row.status == QueueStatus.running
    # started_at 應該還在原時間（毫秒誤差容忍 1 秒）
    delta = abs((row.started_at - started).total_seconds())
    assert delta < 1.0


@pytest.mark.asyncio
async def test_stale_beyond_5min_reclaimed(make_row):
    stale_started = datetime.now(timezone.utc) - timedelta(minutes=12)
    row_id, ep_id = await make_row(
        status=QueueStatus.running,
        started_at=stale_started,
        celery_task_id="task-ghost",
    )
    claim, returned = await _claim_queue_row(ep_id, "task-new")
    assert claim == CLAIM_PROCEED
    assert returned == row_id

    row = await _get(row_id)
    assert row.celery_task_id == "task-new"
    assert row.status == QueueStatus.running
    # started_at 應該被更新成新的
    assert (datetime.now(timezone.utc) - row.started_at).total_seconds() < 5
    assert row.dispatched_at is None


@pytest.mark.asyncio
async def test_cancelled_row_acked_without_work(make_row):
    row_id, ep_id = await make_row(status=QueueStatus.cancelled)
    claim, returned = await _claim_queue_row(ep_id, "task-late")
    assert claim == CLAIM_SKIP_TERMINAL
    assert returned == row_id

    row = await _get(row_id)
    assert row.status == QueueStatus.cancelled
    assert row.celery_task_id is None


@pytest.mark.asyncio
async def test_completed_row_acked_without_work(make_row):
    row_id, ep_id = await make_row(status=QueueStatus.completed)
    claim, returned = await _claim_queue_row(ep_id, "task-late")
    assert claim == CLAIM_SKIP_TERMINAL


@pytest.mark.asyncio
async def test_claim_row_not_found_returns_sentinel():
    ghost = str(uuid.uuid4())
    claim, returned = await _claim_queue_row(ghost, "task-x")
    assert claim == CLAIM_NOT_FOUND
    assert returned is None


# ─── Dispatcher does not pre-mark + dispatched_at memo pad (task 3.1, 8.2) ───


@pytest.mark.asyncio
async def test_dispatcher_does_not_pre_mark_row_as_running(make_row):
    row_id, ep_id = await make_row(status=QueueStatus.pending, position=100)

    with patch("app.workers.dispatcher.get_max_concurrent", return_value=10):
        async with AsyncSessionFactory() as db:
            popped = await _try_pop_one(db)

    assert popped == ep_id

    row = await _get(row_id)
    assert row.status == QueueStatus.pending
    assert row.started_at is None
    assert row.celery_task_id is None
    assert row.dispatched_at is not None


# ─── worker-reliability D3: dispatcher never dispatches ASR for
# externally imported rows (spec: transcription-queue → Requirement
# "Dispatcher never dispatches ASR for externally imported rows") ───


@pytest.mark.asyncio
async def test_external_row_failed_not_dispatched(make_row):
    row_id, ep_id = await make_row(
        status=QueueStatus.pending,
        position=90,
        whisper_model="external:faster-whisper-large-v3-turbo",
    )

    with patch("app.workers.dispatcher.get_max_concurrent", return_value=10):
        async with AsyncSessionFactory() as db:
            popped = await _try_pop_one(db)

    assert popped is None  # 不派 task
    row = await _get(row_id)
    assert row.status == QueueStatus.failed
    assert "重新執行 transcript-import" in (row.error_message or "")
    assert row.dispatched_at is None
    assert row.finished_at is not None


@pytest.mark.asyncio
async def test_normal_asr_row_still_dispatched(make_row):
    row_id, ep_id = await make_row(
        status=QueueStatus.pending, position=91, whisper_model="large-v3"
    )

    with patch("app.workers.dispatcher.get_max_concurrent", return_value=10):
        async with AsyncSessionFactory() as db:
            popped = await _try_pop_one(db)

    assert popped == ep_id
    row = await _get(row_id)
    assert row.status == QueueStatus.pending
    assert row.dispatched_at is not None


@pytest.mark.asyncio
async def test_second_tick_does_not_reselect_already_dispatched_row(make_row):
    """Tick 1 pick R5、commit dispatched_at。Tick 2 不該再 select R5。"""
    row_id, ep_id = await make_row(status=QueueStatus.pending, position=200)

    with patch("app.workers.dispatcher.get_max_concurrent", return_value=10):
        async with AsyncSessionFactory() as db:
            first = await _try_pop_one(db)
        assert first == ep_id

        async with AsyncSessionFactory() as db:
            second = await _try_pop_one(db)
        # 沒別的 pending row → 第二次必然回 None（沒 reselect R5）
        assert second is None

    row = await _get(row_id)
    assert row.dispatched_at is not None
    assert row.status == QueueStatus.pending


@pytest.mark.asyncio
async def test_two_concurrent_dispatchers_skip_locked(make_row):
    """兩個 dispatcher session 同時 claim 同 row：FOR UPDATE SKIP LOCKED
    保證一個拿到、另一個跳過。"""
    row_id, ep_id = await make_row(status=QueueStatus.pending, position=300)

    # 開兩個 session：第一個交易先鎖住 row 但不 commit，第二個 SELECT
    # SKIP LOCKED 應該跳過此 row 並回 None（沒其他 pending）。
    session_a = AsyncSessionFactory()
    session_b = AsyncSessionFactory()
    try:
        with patch("app.workers.dispatcher.get_max_concurrent", return_value=10):
            # A 先進但故意不 commit（手動執行 SELECT FOR UPDATE）
            from sqlalchemy import select
            stmt_a = (
                select(TranscriptionQueue)
                .where(
                    TranscriptionQueue.status == QueueStatus.pending,
                    TranscriptionQueue.dispatched_at.is_(None),
                )
                .order_by(TranscriptionQueue.position.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row_a = (await session_a.execute(stmt_a)).scalar_one_or_none()
            assert row_a is not None
            assert str(row_a.id) == row_id

            # B 同時跑 _try_pop_one：應該 skip_locked → None
            popped_b = await _try_pop_one(session_b)
            assert popped_b is None

            # A 完成 commit
            row_a.dispatched_at = datetime.now(timezone.utc)
            await session_a.commit()
    finally:
        await session_a.close()
        await session_b.close()


@pytest.mark.asyncio
async def test_entry_clears_dispatched_at(make_row):
    """worker entry 把 row 轉 running 同時清掉 dispatched_at。"""
    dispatched = datetime.now(timezone.utc) - timedelta(seconds=10)
    row_id, ep_id = await make_row(
        status=QueueStatus.pending, dispatched_at=dispatched
    )

    claim, _ = await _claim_queue_row(ep_id, "task-entry")
    assert claim == CLAIM_PROCEED

    row = await _get(row_id)
    assert row.dispatched_at is None
    assert row.status == QueueStatus.running


@pytest.mark.asyncio
async def test_terminal_clears_dispatched_at(make_row):
    """終態 transition 也把 dispatched_at 清回 NULL。
    （_mark_queue_finished 路徑）。"""
    from app.workers.tasks import _mark_queue_finished

    # 先設成 running 並（為了測試）灌一個非 NULL dispatched_at
    row_id, ep_id = await make_row(
        status=QueueStatus.running,
        started_at=datetime.now(timezone.utc),
        dispatched_at=datetime.now(timezone.utc),
    )

    await _mark_queue_finished(uuid.UUID(ep_id), QueueStatus.completed)

    row = await _get(row_id)
    assert row.status == QueueStatus.completed
    assert row.dispatched_at is None


# ─── Startup hook: ambiguous + stuck reset (task 5.1, 8.4) ───


@pytest.mark.asyncio
async def test_startup_resets_running_with_null_started_at(make_row):
    """running + started_at IS NULL → reset to pending."""
    row_id, _ = await make_row(
        status=QueueStatus.running, started_at=None, celery_task_id="ghost"
    )
    n = await _reset_ambiguous_and_stuck_rows_async()
    assert n >= 1
    row = await _get(row_id)
    assert row.status == QueueStatus.pending
    assert row.started_at is None
    assert row.celery_task_id is None
    assert row.dispatched_at is None


@pytest.mark.asyncio
async def test_startup_resets_stuck_dispatched_at(make_row):
    """pending + dispatched_at < NOW - 5min → reset dispatched_at=NULL."""
    old = datetime.now(timezone.utc) - timedelta(minutes=12)
    row_id, _ = await make_row(
        status=QueueStatus.pending, dispatched_at=old
    )
    n = await _reset_ambiguous_and_stuck_rows_async()
    assert n >= 1
    row = await _get(row_id)
    assert row.status == QueueStatus.pending
    assert row.dispatched_at is None


@pytest.mark.asyncio
async def test_startup_does_not_reset_fresh_dispatched_at(make_row):
    """pending + dispatched_at < 5min → 不 reset（worker 可能剛要 pick）。"""
    fresh = datetime.now(timezone.utc) - timedelta(seconds=30)
    row_id, _ = await make_row(
        status=QueueStatus.pending, dispatched_at=fresh
    )
    await _reset_ambiguous_and_stuck_rows_async()
    row = await _get(row_id)
    assert row.dispatched_at is not None
