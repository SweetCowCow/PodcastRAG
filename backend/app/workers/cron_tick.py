"""Celery Beat-driven scheduler tick.

Fires once per minute. Each tick:

1. Selects ``show_schedules`` rows with ``enabled=true`` whose
   (frequency, run_time) matches the current UTC moment.
2. For each due show: refreshes its RSS-derived episode list
   (calls ``sync_show_episodes``), records the outcome into
   ``last_refresh_*`` columns.
3. On refresh success, enqueues up to ``max_episodes_per_run`` of the
   newest episodes that are not already represented in the queue
   (excluding completed/running/pending and ignored rows).

Per design "Use a single 1-minute tick instead of per-schedule beat
entries" — Beat has only one entry; per-show due-time logic lives
inside this task.

A failure for one show MUST NOT prevent others in the same tick from
processing — every show is wrapped in its own try/except.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.episode import Episode
from app.models.show_schedule import RefreshStatus, ShowSchedule
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.services.rss_parser import RssParseError
from app.services.sync import sync_show_episodes
from app.workers.celery_app import celery_app
from app.workers.dispatch import enqueue_transcription

logger = logging.getLogger(__name__)

REFRESH_MESSAGE_MAX_LEN = 500


@celery_app.task(name="app.workers.cron_tick.cron_tick")
def cron_tick() -> dict:
    """Beat entry point. Runs the async tick body."""
    return asyncio.run(_run_tick())


async def _run_tick() -> dict:
    now = datetime.now(timezone.utc)
    current_hhmm = now.strftime("%H:%M")
    weekday = now.weekday()

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    processed = 0
    enqueued = 0

    try:
        async with Session() as session:
            schedules = (
                await session.execute(
                    select(ShowSchedule).where(ShowSchedule.enabled.is_(True))
                )
            ).scalars().all()
            schedule_ids = [s.id for s in schedules]

        for schedule_id in schedule_ids:
            try:
                async with Session() as probe:
                    schedule = await probe.get(ShowSchedule, schedule_id)
                    if schedule is None:
                        continue
                    if not _is_due(schedule, current_hhmm, weekday):
                        continue
                    show_id = schedule.show_id
                    max_eps = schedule.max_episodes_per_run

                refresh_ok, added, error_message = await _refresh_show(
                    Session, show_id
                )

                async with Session() as upd:
                    sched = await upd.get(ShowSchedule, schedule_id)
                    if sched is None:
                        continue
                    sched.last_refresh_at = now
                    if refresh_ok:
                        sched.last_refresh_status = RefreshStatus.success
                        sched.last_refresh_message = f"+{added} 集"
                    else:
                        sched.last_refresh_status = RefreshStatus.failed
                        sched.last_refresh_message = (
                            error_message[:REFRESH_MESSAGE_MAX_LEN]
                            if error_message
                            else None
                        )
                    await upd.commit()

                processed += 1
                if not refresh_ok:
                    continue

                enqueued += await _enqueue_latest(Session, show_id, max_eps)
            except Exception:
                logger.exception(
                    "cron_tick: schedule %s failed — continuing", schedule_id
                )
    finally:
        await engine.dispose()

    return {
        "tick_at": now.isoformat(),
        "processed": processed,
        "enqueued": enqueued,
    }


def _is_due(schedule: ShowSchedule, current_hhmm: str, weekday: int) -> bool:
    """Return True if this schedule should fire at this minute.

    ``manual`` frequency always returns False — manual schedules opt
    out of the cron entirely (the schedule row still stores model and
    per-trigger episode cap for the manual UI button).
    """
    if schedule.run_time != current_hhmm:
        return False
    if schedule.frequency == "daily":
        return True
    if schedule.frequency == "weekly":
        return weekday == 0  # Monday
    return False


async def _refresh_show(session_factory, show_id) -> tuple[bool, int, str | None]:
    """Run RSS sync in its own session.

    Returns (success, added_count, error_message). Failure does not
    leak the exception; caller logs the outcome to the schedule row.
    """
    try:
        async with session_factory() as session:
            result = await sync_show_episodes(show_id, session)
            await session.commit()
            return True, int(result.get("added", 0)), None
    except Exception as exc:
        logger.exception("cron_tick: refresh failed for show %s", show_id)
        return False, 0, str(exc)


async def _enqueue_latest(
    session_factory, show_id, max_episodes_per_run: int
) -> int:
    """Enqueue up to N newest episodes that have no queue row yet.

    Excludes episodes already in (completed | running | pending) queue
    rows. Failed/cancelled rows are eligible for re-enqueue (the
    revive path in ``enqueue_transcription`` handles them).
    """
    async with session_factory() as session:
        candidates = (
            await session.execute(
                select(Episode)
                .where(
                    Episode.show_id == show_id,
                    Episode.id.notin_(
                        select(TranscriptionQueue.episode_id).where(
                            TranscriptionQueue.status.in_(
                                (
                                    QueueStatus.completed,
                                    QueueStatus.running,
                                    QueueStatus.pending,
                                )
                            )
                        )
                    ),
                )
                .order_by(Episode.published_at.desc())
                .limit(max_episodes_per_run)
            )
        ).scalars().all()

        enqueued = 0
        for episode in candidates:
            await enqueue_transcription(episode.id, session)
            enqueued += 1
        if enqueued:
            await session.commit()
        return enqueued
