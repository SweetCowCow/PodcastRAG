"""Celery task: import an externally produced transcript for one episode.

external-transcript-bulk-import D3: the admin endpoint validates and
enqueues; this task converts the payload into a `TranscriptionResult` and
persists it through the shared post-ASR seam
(`tasks._persist_transcription_result`), so imported episodes get exactly
the same downstream artifacts as provider-transcribed ones (ASR
corrections, segments, chunks, dual embeddings, summary + topic chain).

Queue row provenance (D2): ensure a `transcription_queue` row exists and
ends `completed` with `whisper_model="external:<model>"`, so
`cron_tick._enqueue_latest` treats the episode as already transcribed and
the admin queue UI shows the external origin. Runs on the default
`control` queue (no explicit route needed).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_chunk import TranscriptChunk
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.services.transcription import TranscriptionResult, TranscriptionSegment
from app.workers.celery_app import celery_app
from app.workers.tasks import (
    ERROR_MESSAGE_MAX_LEN,
    _mark_queue_finished,
    _persist_transcription_result,
)

logger = logging.getLogger(__name__)

EXTERNAL_MODEL_LABEL_PREFIX = "external:"
# transcription_queue.whisper_model is String(50).
_MODEL_LABEL_MAX_LEN = 50

# `_ensure_queue_row` outcomes.
ENSURE_OK = "ok"
ENSURE_CONFLICT = "conflict"
ENSURE_NOT_FOUND = "not_found"


def _model_label(payload_model: str) -> str:
    return (EXTERNAL_MODEL_LABEL_PREFIX + payload_model)[:_MODEL_LABEL_MAX_LEN]


async def _ensure_queue_row(
    ep_uuid: uuid.UUID, model_label: str, task_id: str | None
) -> str:
    """Create or revive the queue row and put it in `running` for this import.

    - no row → create one (running, external model label)
    - failed / cancelled / completed → reuse: back to running with the
      external label (re-import is an idempotent overwrite, D3)
    - pending / running → conflict: an ASR transcription is in flight; the
      endpoint already rejects this with 409, this is the task-level
      double-check against races
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(TranscriptionQueue)
                    .where(TranscriptionQueue.episode_id == ep_uuid)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc)

            if row is None:
                episode = await session.get(Episode, ep_uuid)
                if episode is None:
                    return ENSURE_NOT_FOUND
                next_position = (
                    await session.scalar(
                        select(
                            func.coalesce(func.max(TranscriptionQueue.position), 0)
                        )
                    )
                ) + 1
                row = TranscriptionQueue(
                    episode_id=ep_uuid,
                    show_id=episode.show_id,
                    status=QueueStatus.running,
                    position=next_position,
                    whisper_model=model_label,
                    started_at=now,
                    celery_task_id=task_id,
                )
                session.add(row)
                await session.commit()
                return ENSURE_OK

            if row.status in (QueueStatus.pending, QueueStatus.running):
                return ENSURE_CONFLICT

            row.status = QueueStatus.running
            row.started_at = now
            row.finished_at = None
            row.error_message = None
            row.whisper_model = model_label
            row.celery_task_id = task_id
            row.dispatched_at = None
            await session.commit()
            return ENSURE_OK
    finally:
        await engine.dispose()


async def _mark_import_failed(
    ep_uuid: uuid.UUID, message: str, model_label: str
) -> None:
    """Downstream failure: transcript → failed with the error recorded, no
    partial chunks left behind (mirrors `_run`'s permanent-error handler)."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            transcript = (
                await session.execute(
                    select(Transcript).where(Transcript.episode_id == ep_uuid)
                )
            ).scalar_one_or_none()
            if transcript is not None:
                await session.execute(
                    delete(TranscriptChunk).where(
                        TranscriptChunk.transcript_id == transcript.id
                    )
                )
                transcript.status = TranscriptStatus.failed
                transcript.error_message = message
                await session.commit()
    finally:
        await engine.dispose()

    await _mark_queue_finished(
        ep_uuid, QueueStatus.failed, message, model_label=model_label
    )


@celery_app.task(
    name="app.workers.import_task.import_external_transcript",
    bind=True,
)
def import_external_transcript(self, episode_id: str, payload: dict) -> dict:
    """One-shot import — no autoretry: the local import script owns retries
    of its failed list, and a blind Celery retry would just re-burn the
    embedding call."""
    ep_uuid = uuid.UUID(episode_id)
    label = _model_label(str(payload.get("model") or "unknown"))

    # Build the TranscriptionResult BEFORE touching the queue row, so a
    # malformed payload fails without leaving a running row behind.
    result = TranscriptionResult(
        text=payload["text"],
        language=payload.get("language"),
        segments=[
            TranscriptionSegment(
                start=float(seg["start"]),
                end=float(seg["end"]),
                text=seg["text"],
            )
            for seg in payload["segments"]
        ],
    )

    ensure = asyncio.run(
        _ensure_queue_row(ep_uuid, label, task_id=self.request.id)
    )
    if ensure == ENSURE_NOT_FOUND:
        logger.error(
            "import_external_transcript: episode %s 不存在", episode_id
        )
        return {"status": "not_found", "episode_id": episode_id}
    if ensure == ENSURE_CONFLICT:
        logger.warning(
            "import_external_transcript: queue row for %s is pending/running "
            "— aborting import",
            episode_id,
        )
        return {"status": "conflict", "episode_id": episode_id}

    try:
        return asyncio.run(
            _persist_transcription_result(
                episode_id, result, queue_model_label=label
            )
        )
    except Exception as exc:
        logger.exception(
            "import_external_transcript failed episode=%s", episode_id
        )
        message = str(exc)[:ERROR_MESSAGE_MAX_LEN]
        asyncio.run(_mark_import_failed(ep_uuid, message, label))
        return {
            "status": "failed",
            "episode_id": episode_id,
            "error": message,
        }
