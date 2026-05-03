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


@celery_app.task(
    name="app.workers.summary_task.generate_episode_summary",
    bind=True,
    autoretry_for=SUMMARY_TRANSIENT_ERRORS,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def generate_episode_summary(self, episode_id: str) -> dict:
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
                    "summary task: %s already running, skipping", episode_id
                )
                return {"skipped": "already_running"}

            ep.ai_summary_status = AiSummaryStatus.running.value
            await db.commit()

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
        except SUMMARY_TRANSIENT_ERRORS:
            # Re-raise so Celery autoretry triggers; only mark failed when
            # retries are exhausted (handled in on_failure path below).
            if task.request.retries >= task.max_retries:
                await _mark_failed(Session, ep_uuid, model_name=step.model)
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
                await _mark_failed(Session, ep_uuid, model_name=None)
            except Exception:
                logger.exception("summary task: failed to mark row failed")
        raise
    finally:
        await engine.dispose()


async def _mark_failed(Session, ep_uuid: uuid.UUID, *, model_name: str | None) -> None:
    async with Session() as db:
        ep = await db.get(Episode, ep_uuid)
        if ep is None:
            return
        ep.ai_summary_status = AiSummaryStatus.failed.value
        ep.ai_summary_generated_at = datetime.now(timezone.utc)
        if model_name is not None:
            ep.ai_summary_model = model_name
        await db.commit()
