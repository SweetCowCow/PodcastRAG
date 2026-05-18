"""Celery task: classify topic_label for every segment of one episode.

Idempotent: short-circuits if every segment already has a topic_label.
Chained off the transcription pipeline via _mark_queue_finished in tasks.py
(in parallel with the summary task — no dependency between them).

Per-batch commit lives inside `classify_episode`, so even if this task is
killed mid-episode (container restart) progress is preserved on disk.
The next invocation runs with `skip_labelled=True` and only re-classifies
the remaining NULL segments.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import httpx
import openai
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.transcript import Transcript
from app.models.transcript_segment import TranscriptSegment
from app.services.topic_segmentation import classify_episode
from app.workers.celery_app import celery_app
from app.workers.failure_hooks import (
    check_circuit_or_retry,
    classify_and_short_circuit,
    record_task_failure_unless_logged,
)

logger = logging.getLogger(__name__)


class _TopicTask(celery_app.Task):
    """task-failure-monitoring-and-circuit-breaker on_failure 寫 log。"""

    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # type: ignore[override]
        record_task_failure_unless_logged(
            task_name="app.workers.topic_task.classify_episode_topics",
            args=args,
            exc=exc,
            provider_id="aihub",
            retry_count=int(self.request.retries or 0),
        )

TOPIC_TRANSIENT_ERRORS = (
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
    base=_TopicTask,
    name="app.workers.topic_task.classify_episode_topics",
    bind=True,
    autoretry_for=TOPIC_TRANSIENT_ERRORS,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    priority=2,
)
def classify_episode_topics(self, episode_id: str) -> dict:
    # task-failure-monitoring-and-circuit-breaker task 5.1: aihub circuit
    # check —— open 時自我 retry 5 min 後再來。
    check_circuit_or_retry(self, "aihub")
    # celery-routing-and-dispatcher-fix task 4.2 (defensive entry
    # idempotency): topic task 不寫 transcription_queue，自身的 entry
    # idempotency 由 `_run` 開頭「unlabelled == 0 短路」保證——重複 task
    # 進來時所有 segment 都已 labelled、會走 already_done 分支立刻 ack。
    try:
        return asyncio.run(_run(episode_id))
    except Exception as exc:
        # task 3.3: permanent → log + re-raise without autoretry path.
        if classify_and_short_circuit(
            self,
            exc,
            task_name="app.workers.topic_task.classify_episode_topics",
            args=(episode_id,),
            provider_id="aihub",
        ):
            # Re-raise without calling self.retry to short-circuit
            # Celery's autoretry. on_failure base class also fires; the
            # duplicate-write is acceptable per spec (idempotent for
            # threshold counting — both rows share same provider_id +
            # failure_type so still trigger one open() transition).
            raise
        raise


async def _run(episode_id: str) -> dict:
    ep_uuid = uuid.UUID(episode_id)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        # Idempotency: short-circuit if all segments already labelled.
        async with Session() as db:
            transcript = (
                await db.execute(
                    select(Transcript).where(Transcript.episode_id == ep_uuid)
                )
            ).scalar_one_or_none()
            if transcript is None:
                logger.warning("topic task: no transcript for %s", episode_id)
                return {"skipped": "no_transcript"}

            unlabelled = (
                await db.execute(
                    select(func.count())
                    .select_from(TranscriptSegment)
                    .where(
                        TranscriptSegment.transcript_id == transcript.id,
                        TranscriptSegment.topic_label.is_(None),
                    )
                )
            ).scalar_one()

            if unlabelled == 0:
                logger.info(
                    "topic task: %s already fully labelled, skipping",
                    episode_id,
                )
                return {"skipped": "already_done"}

        # Run classification (per-batch commit happens inside).
        # skip_labelled=True so we don't re-pay LLM cost on already-classified
        # batches when this task is retried after a partial run.
        async with Session() as db:
            label_map = await classify_episode(
                db, ep_uuid, skip_labelled=True
            )

        logger.info(
            "topic task: %s done — %d segments classified",
            episode_id,
            len(label_map),
        )
        return {"ok": True, "classified": len(label_map)}
    finally:
        await engine.dispose()
