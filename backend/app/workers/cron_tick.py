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
from datetime import datetime, timedelta, timezone

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
from app.workers.throttle import release_global_slot

logger = logging.getLogger(__name__)

REFRESH_MESSAGE_MAX_LEN = 500
STALE_THRESHOLD_MINUTES = 30
STALE_ERROR_MESSAGE = "Stale task — worker message lost"
INSPECT_TIMEOUT_SECONDS = 5


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
    stale_marked = 0

    try:
        try:
            stale_marked = await _detect_stale_running(Session)
        except Exception:
            logger.warning(
                "cron_tick: stale detection raised — skipping this tick",
                exc_info=True,
            )

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
        "stale_marked": stale_marked,
    }


async def _detect_stale_running(session_factory) -> int:
    """Find queue rows stuck in ``running`` longer than the threshold and
    not currently being processed by any Celery worker, mark them
    ``failed`` and release their throttle slots.

    Returns the count of rows marked stale. If Celery inspect fails,
    times out, or returns no workers at all (broker unreachable), the
    function logs a warning and returns 0 without touching any rows.
    """
    inspect = celery_app.control.inspect(timeout=INSPECT_TIMEOUT_SECONDS)
    try:
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
    except Exception:
        logger.warning(
            "cron_tick: inspect raised — skipping stale detection", exc_info=True
        )
        return 0

    if not active and not reserved:
        logger.warning(
            "cron_tick: inspect returned no workers — skipping stale detection"
        )
        return 0

    running_ids: set[str] = set()
    for tasks in active.values():
        running_ids.update(t.get("id") for t in (tasks or []) if t.get("id"))
    for tasks in reserved.values():
        running_ids.update(t.get("id") for t in (tasks or []) if t.get("id"))

    threshold = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MINUTES)
    marked = 0

    async with session_factory() as session:
        candidates = (
            await session.execute(
                select(TranscriptionQueue).where(
                    TranscriptionQueue.status == QueueStatus.running,
                    TranscriptionQueue.started_at < threshold,
                )
            )
        ).scalars().all()

        for row in candidates:
            if row.celery_task_id and row.celery_task_id in running_ids:
                continue
            row.status = QueueStatus.failed
            row.finished_at = datetime.now(timezone.utc)
            row.error_message = STALE_ERROR_MESSAGE
            marked += 1
            try:
                release_global_slot(str(row.id))
            except Exception:
                logger.exception(
                    "cron_tick: release_global_slot failed for queue_id=%s",
                    row.id,
                )

        if marked:
            await session.commit()
            logger.info("cron_tick: stale detected: %d rows", marked)

    return marked


def _is_due(schedule: ShowSchedule, current_hhmm: str, weekday: int) -> bool:
    """Return True if this schedule should fire at this minute.

    Weekly schedules fire only when the current UTC weekday matches
    ``schedule.day_of_week`` (0=Monday..6=Sunday per Python
    ``datetime.weekday()``). ``manual`` frequency always returns
    False — manual schedules opt out of the cron entirely (the
    schedule row still stores model and per-trigger episode cap for
    the manual UI button).
    """
    if schedule.run_time != current_hhmm:
        return False
    if schedule.frequency == "daily":
        return True
    if schedule.frequency == "weekly":
        return weekday == schedule.day_of_week
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
