import asyncio
import logging
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import openai
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_chunk import TranscriptChunk
from app.models.transcript_segment import TranscriptSegment
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.services import storage
from app.services import tokenizer
from app.services.chunking import build_chunks
from app.services.ai_step_resolver import get_step_config
from app.services.embedding import embed_texts, embed_texts_dual
from app.services.rss_parser import RssParseError
from app.services.storage import StorageError
from app.services.transcription import get_provider
from app.workers.celery_app import celery_app
from app.workers.lifecycle import deregister_active_row, register_active_row
from app.workers.throttle import (
    acquire_global_slot,
    acquire_show_lock,
    release_global_slot,
    release_show_lock,
)

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX_LEN = 2000

# celery-routing-and-dispatcher-fix: worker idempotency window. 若 row 已
# status=running 且 started_at 在這個區間內，視為仍在處理 → 直接 ack。
WORKER_CLAIM_STALE_AFTER = timedelta(minutes=5)


class ClaimDecision:
    PROCEED = "proceed"
    SKIP_DUPLICATE = "skip_duplicate"
    SKIP_TERMINAL = "skip_terminal"
    NOT_FOUND = "not_found"
    RECLAIMED = "reclaimed"


_TERMINAL_STATES = {
    QueueStatus.completed,
    QueueStatus.failed,
    QueueStatus.cancelled,
}

TRANSIENT_ERRORS = (
    httpx.HTTPError,
    httpx.TimeoutException,
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    asyncio.TimeoutError,
    ConnectionError,
)

PERMANENT_ERRORS = (
    RssParseError,
    StorageError,
    FileNotFoundError,
    subprocess.CalledProcessError,
    openai.AuthenticationError,
    openai.BadRequestError,
)


@celery_app.task(
    name="app.workers.tasks.transcribe_episode",
    bind=True,
    autoretry_for=TRANSIENT_ERRORS,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    # celery-routing-and-dispatcher-fix: transcribe 走獨立 transcribe queue + 高 priority。
    queue="transcribe",
    priority=9,
)
def transcribe_episode(self, episode_id: str) -> dict:
    # celery-routing-and-dispatcher-fix: atomic idempotent entry.
    # 任何重複 task / cancelled row / 不存在 row 都在這裡 ack & exit，
    # 後續才碰外部 I/O（Whisper / OpenAI）。
    queue_row_id, decision = asyncio.run(
        _claim_queue_row(episode_id, self.request.id)
    )
    if decision == ClaimDecision.NOT_FOUND:
        logger.error(
            "transcribe_episode: queue row for %s 不存在",
            episode_id,
        )
        return {"status": "not_found", "episode_id": episode_id}
    if decision == ClaimDecision.SKIP_DUPLICATE:
        return {"status": "duplicate_skipped", "episode_id": episode_id}
    if decision == ClaimDecision.SKIP_TERMINAL:
        return {"status": "cancelled", "episode_id": episode_id}
    # PROCEED / RECLAIMED → continue. row now has status=running + this task_id.

    show_id = asyncio.run(_lookup_show_id(episode_id))
    if show_id is None:
        logger.error("transcribe_episode: episode %s 不存在", episode_id)
        return {"status": "not_found", "episode_id": episode_id}

    if not acquire_global_slot(queue_row_id):
        raise self.retry(countdown=15, max_retries=None)

    register_active_row(queue_row_id)
    try:
        if not acquire_show_lock(show_id):
            raise self.retry(countdown=60, max_retries=None)
        try:
            return asyncio.run(_run(episode_id))
        finally:
            release_show_lock(show_id)
    finally:
        deregister_active_row(queue_row_id)
        release_global_slot(queue_row_id)


async def _write_celery_task_id(
    episode_id: str, task_id: str
) -> tuple[str | None, bool]:
    """Write ``celery_task_id`` onto the queue row at task start.

    Returns ``(queue_row_id, is_cancelled)``:
    - ``queue_row_id`` is the str(UUID) of the row, or None if no row exists.
      Callers use this as the throttle slot ownership key so release works
      even when ``celery_task_id`` later gets cleared by graceful shutdown.
    - ``is_cancelled`` is True when the row is already cancelled so a
      force-cancel that arrived before the worker picked up the task is
      honoured without acquiring slots or processing audio.
    """
    ep_uuid = uuid.UUID(episode_id)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(TranscriptionQueue).where(
                        TranscriptionQueue.episode_id == ep_uuid
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None, False
            row.celery_task_id = task_id
            await session.commit()
            return str(row.id), row.status == QueueStatus.cancelled
    finally:
        await engine.dispose()


async def _claim_queue_row(
    episode_id: str, task_id: str
) -> tuple[str | None, str]:
    """Atomic idempotent entry: lock the queue row and decide whether to run.

    celery-routing-and-dispatcher-fix: dispatcher 不再預先 set running，
    所以 worker task 進場時必須自己 transition row。用 SELECT FOR UPDATE
    防止同一 episode 兩個 task 同時通過 check。

    Returns ``(queue_row_id, decision)`` where decision is one of:
    - ``PROCEED`` — claimed pending row; row now status=running with this task id
    - ``SKIP_DUPLICATE`` — another live task is already processing (within 5 min)
    - ``RECLAIMED`` — row was running but went stale (>5 min); took ownership
    - ``SKIP_TERMINAL`` — row is cancelled/completed/failed; nothing to do
    - ``NOT_FOUND`` — no queue row exists for this episode
    """
    ep_uuid = uuid.UUID(episode_id)
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
            if row is None:
                return None, ClaimDecision.NOT_FOUND

            row_id = str(row.id)
            now = datetime.now(timezone.utc)

            if row.status in _TERMINAL_STATES or row.status == QueueStatus.ignored:
                # cancelled / completed / failed / ignored → ack & return
                return row_id, ClaimDecision.SKIP_TERMINAL

            if row.status == QueueStatus.running:
                started_at = row.started_at
                # 視同 live 的條件：started_at 在 5 min 內。
                if started_at is not None:
                    # Normalize tz so naive timestamps from old rows compare safely.
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    if now - started_at <= WORKER_CLAIM_STALE_AFTER:
                        logger.warning(
                            "transcribe_episode: duplicate task for episode=%s "
                            "(existing_task=%s, this_task=%s, started_at=%s) — ack & skip",
                            episode_id,
                            row.celery_task_id,
                            task_id,
                            started_at.isoformat(),
                        )
                        return row_id, ClaimDecision.SKIP_DUPLICATE
                # 視同 stale：started_at IS NULL 或 > 5 min → 取回所有權。
                logger.warning(
                    "transcribe_episode: reclaiming stale running row for "
                    "episode=%s (prev_task=%s, this_task=%s, started_at=%s)",
                    episode_id,
                    row.celery_task_id,
                    task_id,
                    started_at.isoformat() if started_at else "NULL",
                )
                row.started_at = now
                row.celery_task_id = task_id
                await session.commit()
                return row_id, ClaimDecision.RECLAIMED

            # status == pending → 正常通路
            row.status = QueueStatus.running
            row.started_at = now
            row.celery_task_id = task_id
            await session.commit()
            return row_id, ClaimDecision.PROCEED
    finally:
        await engine.dispose()


async def _mark_queue_started(episode_id: str) -> None:
    """Set ``started_at = now`` on the queue row if not already set."""
    ep_uuid = uuid.UUID(episode_id)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(TranscriptionQueue).where(
                        TranscriptionQueue.episode_id == ep_uuid
                    )
                )
            ).scalar_one_or_none()
            if row is not None and row.started_at is None:
                row.started_at = datetime.now(timezone.utc)
                await session.commit()
    finally:
        await engine.dispose()


async def _is_queue_cancelled(session, ep_uuid: uuid.UUID) -> bool:
    row = (
        await session.execute(
            select(TranscriptionQueue).where(
                TranscriptionQueue.episode_id == ep_uuid
            )
        )
    ).scalar_one_or_none()
    return row is not None and row.status == QueueStatus.cancelled


async def _mark_queue_finished(
    ep_uuid: uuid.UUID, status: QueueStatus, error: str | None = None
) -> None:
    """Write back terminal state to the queue row.

    On successful transcription completion, chain-enqueue the AI summary task.
    Summary failures must NOT write back to the transcription queue (D2).
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    chain_summary = False
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(TranscriptionQueue).where(
                        TranscriptionQueue.episode_id == ep_uuid
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return
            if row.status == QueueStatus.cancelled:
                return
            row.status = status
            row.finished_at = datetime.now(timezone.utc)
            row.error_message = error[:ERROR_MESSAGE_MAX_LEN] if error else None
            await session.commit()
            chain_summary = status == QueueStatus.completed
    finally:
        await engine.dispose()

    if chain_summary:
        try:
            from app.workers.summary_task import generate_episode_summary

            generate_episode_summary.delay(str(ep_uuid))
            logger.info("chained summary task enqueued for %s", ep_uuid)
        except Exception:
            logger.exception(
                "failed to chain-enqueue summary for %s — non-fatal", ep_uuid
            )
        try:
            from app.workers.topic_task import classify_episode_topics

            classify_episode_topics.delay(str(ep_uuid))
            logger.info("chained topic task enqueued for %s", ep_uuid)
        except Exception:
            logger.exception(
                "failed to chain-enqueue topic classification for %s — non-fatal",
                ep_uuid,
            )


async def _lookup_show_id(episode_id: str) -> str | None:
    ep_uuid = uuid.UUID(episode_id)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            episode = await session.get(Episode, ep_uuid)
            return str(episode.show_id) if episode is not None else None
    finally:
        await engine.dispose()


async def _run(episode_id: str) -> dict:
    ep_uuid = uuid.UUID(episode_id)
    temp_audio_path: str | None = None

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as session:
            if await _is_queue_cancelled(session, ep_uuid):
                logger.info(
                    "transcribe_episode: queue row for %s is cancelled — aborting",
                    episode_id,
                )
                return {"status": "cancelled", "episode_id": episode_id}

            episode = (
                await session.execute(
                    select(Episode)
                    .options(selectinload(Episode.show))
                    .where(Episode.id == ep_uuid)
                )
            ).scalar_one_or_none()
            if episode is None:
                logger.error("transcribe_episode: episode %s 不存在", episode_id)
                return {"status": "not_found", "episode_id": episode_id}

            transcript = (
                await session.execute(
                    select(Transcript).where(Transcript.episode_id == ep_uuid)
                )
            ).scalar_one_or_none()
            if transcript is None:
                transcript = Transcript(
                    episode_id=ep_uuid, status=TranscriptStatus.processing
                )
                session.add(transcript)
            else:
                transcript.status = TranscriptStatus.processing
                transcript.error_message = None
            await session.commit()
            transcript_id = transcript.id
            audio_storage_key = episode.audio_storage_key
            audio_url = episode.audio_url
            show_language = episode.show.language if episode.show else None

        try:
            if not audio_storage_key:
                audio_storage_key = storage.upload_from_url(audio_url)
                async with Session() as session:
                    ep = await session.get(Episode, ep_uuid)
                    if ep is not None:
                        ep.audio_storage_key = audio_storage_key
                        await session.commit()

            temp_audio_path = storage.download_to_temp(audio_storage_key)

            async with Session() as session:
                transcription_cfg = await get_step_config(session, "transcription")
            provider = get_provider(transcription_cfg)
            result = await provider.transcribe(temp_audio_path, language=show_language)

            async with Session() as session:
                if await _is_queue_cancelled(session, ep_uuid):
                    logger.info(
                        "transcribe_episode: queue row for %s cancelled mid-task "
                        "— skipping artifact writes",
                        episode_id,
                    )
                    return {"status": "cancelled", "episode_id": episode_id}

                await session.execute(
                    delete(TranscriptChunk).where(
                        TranscriptChunk.transcript_id == transcript_id
                    )
                )
                await session.execute(
                    delete(TranscriptSegment).where(
                        TranscriptSegment.transcript_id == transcript_id
                    )
                )
                segment_rows: list[TranscriptSegment] = []
                for seg in result.segments:
                    row = TranscriptSegment(
                        transcript_id=transcript_id,
                        start_time=seg.start,
                        end_time=seg.end,
                        text=seg.text,
                    )
                    session.add(row)
                    segment_rows.append(row)
                await session.flush()

                chunk_drafts = build_chunks(segment_rows)
                if chunk_drafts:
                    embedding_cfg = await get_step_config(session, "embedding")
                    # r3-4 dual-write: populate `embedding` (1536 legacy) and
                    # `embedding_v2` (3072 v3-large) in the same write pass so
                    # rollback via RAG_USE_EMBEDDING_V2=false still finds rows.
                    legacy_vecs, v2_vecs = await asyncio.to_thread(
                        embed_texts_dual,
                        [c.text for c in chunk_drafts],
                        embedding_cfg,
                    )
                else:
                    legacy_vecs = []
                    v2_vecs = []
                if chunk_drafts:
                    await tokenizer.load_dictionary(session)
                for idx, draft in enumerate(chunk_drafts):
                    tokens = tokenizer.tokenize(draft.text)
                    legacy_vec = (
                        legacy_vecs[idx] if legacy_vecs is not None else None
                    )
                    v2_vec = v2_vecs[idx] if v2_vecs is not None else None
                    chunk = TranscriptChunk(
                        transcript_id=transcript_id,
                        chunk_index=idx,
                        start_time=draft.start_time,
                        end_time=draft.end_time,
                        text=draft.text,
                        embedding=legacy_vec,
                        embedding_v2=v2_vec,
                        segment_ids=draft.segment_ids,
                    )
                    chunk.text_tsvector = func.to_tsvector(
                        "simple", " ".join(tokens)
                    )
                    session.add(chunk)

                t = await session.get(Transcript, transcript_id)
                if t is not None:
                    t.status = TranscriptStatus.completed
                    t.language = result.language or show_language
                    t.content = result.text
                    t.error_message = None
                    t.transcribed_at = datetime.now(timezone.utc)
                await session.commit()

            await _mark_queue_finished(ep_uuid, QueueStatus.completed)

            return {
                "status": "completed",
                "episode_id": episode_id,
                "segments": len(result.segments),
                "chunks": len(chunk_drafts),
            }

        except PERMANENT_ERRORS as exc:
            logger.exception(
                "transcribe_episode permanent-failed episode=%s", episode_id
            )
            message = str(exc)[:ERROR_MESSAGE_MAX_LEN]
            async with Session() as session:
                await session.execute(
                    delete(TranscriptChunk).where(
                        TranscriptChunk.transcript_id == transcript_id
                    )
                )
                t = await session.get(Transcript, transcript_id)
                if t is not None:
                    t.status = TranscriptStatus.failed
                    t.error_message = message
                await session.commit()
            await _mark_queue_finished(ep_uuid, QueueStatus.failed, message)
            return {
                "status": "failed",
                "episode_id": episode_id,
                "error": message,
            }

        finally:
            if temp_audio_path:
                try:
                    os.unlink(temp_audio_path)
                except OSError:
                    pass

    finally:
        await engine.dispose()
