"""Celery task: generate AI summary for one episode (D2 + D6).

Idempotent: if status=done already, short-circuit. Chained off the
transcription pipeline via _mark_queue_finished in tasks.py.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

import httpx
import openai
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.episode import AiSummaryStatus, Episode
from app.models.transcript import Transcript
from app.models.transcript_segment import TranscriptSegment
from app.services.ai_step_resolver import get_step_config
from app.services.summary_pipeline import SegmentInput, run_summary
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

SUMMARY_TRANSIENT_ERRORS = (
    httpx.HTTPError,
    httpx.TimeoutException,
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
    asyncio.TimeoutError,
    ConnectionError,
)

SUMMARY_ERROR_MAX_LEN = 1000


def _truncate_error(exc: BaseException) -> str:
    return repr(exc)[:SUMMARY_ERROR_MAX_LEN]


class SummaryTask(celery_app.Task):
    """Custom Task class so on_failure fires even for non-autoretry exceptions
    (programming errors, SIGKILL surrogate exceptions, etc.). Marks the row
    failed + writes ai_summary_error so the admin queue tab + cron-tick
    stale recovery have a clear signal."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # type: ignore[override]
        episode_id = args[0] if args else kwargs.get("episode_id")
        if not episode_id:
            logger.warning(
                "summary on_failure: no episode_id in args/kwargs — task_id=%s",
                task_id,
            )
            return
        try:
            asyncio.run(_mark_failed_from_on_failure(episode_id, exc))
        except Exception:
            logger.exception(
                "summary on_failure: handler crashed for episode %s",
                episode_id,
            )


async def _mark_failed_from_on_failure(episode_id: str, exc: BaseException) -> None:
    """Run by Task.on_failure to record terminal failure on the row.

    Skips rows that are already 'done' (the failure was on a redundant retry
    of an already-completed row, which can happen with at-least-once delivery).
    """
    try:
        ep_uuid = uuid.UUID(episode_id)
    except (ValueError, TypeError):
        logger.warning(
            "summary on_failure: bad episode_id %r — skipping", episode_id
        )
        return
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            ep = await db.get(Episode, ep_uuid)
            if ep is None:
                return
            if ep.ai_summary_status == AiSummaryStatus.done.value:
                logger.info(
                    "summary on_failure: %s already done — leaving row alone",
                    episode_id,
                )
                return
            ep.ai_summary_status = AiSummaryStatus.failed.value
            ep.ai_summary_generated_at = datetime.now(timezone.utc)
            ep.ai_summary_error = _truncate_error(exc)
            await db.commit()
    finally:
        await engine.dispose()


@celery_app.task(
    base=SummaryTask,
    name="app.workers.summary_task.generate_episode_summary",
    bind=True,
    autoretry_for=SUMMARY_TRANSIENT_ERRORS,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    priority=2,
)
def generate_episode_summary(self, episode_id: str) -> dict:
    # celery-routing-and-dispatcher-fix task 4.2 (defensive entry
    # idempotency): summary task 不寫 transcription_queue，由 `_run`
    # 開頭檢查 ai_summary_status in (done, running) 短路。重複 task
    # 進來會走 already_done / already_running 分支立刻 ack。
    return asyncio.run(_run(self, episode_id))


async def _run(task, episode_id: str) -> dict:
    ep_uuid = uuid.UUID(episode_id)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        # Step 1: idempotency short-circuit (D6).
        async with Session() as db:
            ep = await db.get(Episode, ep_uuid)
            if ep is None:
                logger.warning("summary task: episode %s not found", episode_id)
                return {"skipped": "missing"}

            if (
                ep.ai_summary_status == AiSummaryStatus.done.value
                and ep.ai_summary
            ):
                logger.info("summary task: %s already done, skipping", episode_id)
                return {"skipped": "already_done"}

            if ep.ai_summary_status == AiSummaryStatus.running.value:
                logger.warning(
                    "summary task: %s already running (started_at=%s), skipping",
                    episode_id,
                    ep.ai_summary_started_at,
                )
                return {"skipped": "already_running"}

            ep.ai_summary_status = AiSummaryStatus.running.value
            ep.ai_summary_started_at = datetime.now(timezone.utc)
            await db.commit()
            logger.debug(
                "summary task: %s entered running at %s",
                episode_id,
                ep.ai_summary_started_at,
            )

        # Step 2: load transcript segments.
        async with Session() as db:
            transcript = (
                await db.execute(
                    select(Transcript).where(Transcript.episode_id == ep_uuid)
                )
            ).scalar_one_or_none()
            if transcript is None:
                await _mark_failed(Session, ep_uuid, model_name=None)
                logger.error("summary task: no transcript for %s", episode_id)
                return {"failed": "no_transcript"}

            seg_rows = (
                await db.execute(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.transcript_id == transcript.id)
                    .order_by(TranscriptSegment.start_time.asc())
                )
            ).scalars().all()
            segments = [
                SegmentInput(text=s.text, start_time=s.start_time)
                for s in seg_rows
            ]

            step = await get_step_config(db, "summary")

        if not segments:
            await _mark_failed(Session, ep_uuid, model_name=step.model)
            logger.error("summary task: empty segments for %s", episode_id)
            return {"failed": "empty_segments"}

        # Step 3: run pipeline (LLM calls happen here; will raise on transient
        # errors → Celery autoretry_for catches and retries).
        try:
            summary = await run_summary(
                segments,
                base_url=step.base_url,
                api_key=step.api_key,
                model=step.model,
            )
        except SUMMARY_TRANSIENT_ERRORS as exc:
            # Re-raise so Celery autoretry triggers; only mark failed when
            # retries are exhausted. (Task.on_failure also marks failed as a
            # safety net for non-transient exceptions.)
            if task.request.retries >= task.max_retries:
                await _mark_failed(Session, ep_uuid, model_name=step.model, exc=exc)
            raise

        # Step 4: persist done.
        async with Session() as db:
            ep = await db.get(Episode, ep_uuid)
            if ep is None:
                return {"failed": "episode_vanished"}
            ep.ai_summary = summary
            ep.ai_summary_status = AiSummaryStatus.done.value
            ep.ai_summary_generated_at = datetime.now(timezone.utc)
            ep.ai_summary_model = step.model
            ep.ai_summary_error = None
            await db.commit()

        logger.info(
            "summary task: %s done (%d chars)", episode_id, len(summary)
        )
        return {"ok": True, "chars": len(summary)}

    except Exception as exc:
        # Non-transient (e.g. AiStepNotConfiguredError, programming errors)
        # land here. Mark failed and don't retry.
        if not isinstance(exc, SUMMARY_TRANSIENT_ERRORS):
            try:
                await _mark_failed(Session, ep_uuid, model_name=None, exc=exc)
            except Exception:
                logger.exception("summary task: failed to mark row failed")
        raise
    finally:
        await engine.dispose()


async def _mark_failed(
    Session,
    ep_uuid: uuid.UUID,
    *,
    model_name: str | None,
    exc: BaseException | None = None,
) -> None:
    async with Session() as db:
        ep = await db.get(Episode, ep_uuid)
        if ep is None:
            return
        ep.ai_summary_status = AiSummaryStatus.failed.value
        ep.ai_summary_generated_at = datetime.now(timezone.utc)
        if model_name is not None:
            ep.ai_summary_model = model_name
        if exc is not None:
            ep.ai_summary_error = _truncate_error(exc)
        await db.commit()
