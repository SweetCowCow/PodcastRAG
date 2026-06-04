import asyncio
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone

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
from app.services import asr_correction
from app.services import asr_detection_backfill
from app.services import asr_homophone
from app.services.chunking import build_chunks
from app.services.ai_step_resolver import get_step_config
from app.services.embedding import embed_texts, embed_texts_dual
from app.services.rss_parser import RssParseError
from app.services.storage import StorageError
from app.services.transcription import get_provider
from app.workers.celery_app import celery_app
from app.workers.failure_hooks import (
    check_circuit_or_retry,
    classify_and_short_circuit,
    record_task_failure,
    record_task_failure_unless_logged,
)
from app.workers.lifecycle import deregister_active_row, register_active_row
from app.workers.throttle import (
    acquire_global_slot,
    acquire_show_lock,
    release_global_slot,
    release_show_lock,
)

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX_LEN = 2000

# celery-routing-and-dispatcher-fix: worker entry idempotency 視窗。
# 若該 row 已 status=running 且 started_at 在此視窗內 → 視為重複 task，
# 直接 ack 不重跑（防 broker redeliver 同訊息 / dispatcher race 漏網之魚）。
# 寫死 5 分鐘——窗口是「合理任務啟動時間 + retry buffer」的物理上限，
# 不該被 ops 外部隨便調動（要調走 source review）。
WORKER_ENTRY_DUPLICATE_WINDOW_SECONDS = 300

# Sentinel return tokens for `_claim_queue_row`.
CLAIM_PROCEED = "proceed"
CLAIM_SKIP_DUPLICATE = "skip_duplicate"
CLAIM_SKIP_TERMINAL = "skip_terminal"
CLAIM_NOT_FOUND = "not_found"

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


class _TranscribeEpisodeTask(celery_app.Task):
    """task-failure-monitoring-and-circuit-breaker: 統一寫 task_failure_log。

    on_failure 不分類 transient/permanent：那由 try/except 路徑決定。這裡
    只負責「沒人接到的 final failure」也留下一筆紀錄。重複寫(短時間 retry
    短路 + on_failure final 兩個入口)由 failure_log 的 cooldown 保證。
    """

    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # type: ignore[override]
        record_task_failure_unless_logged(
            task_name="app.workers.tasks.transcribe_episode",
            args=args,
            exc=exc,
            provider_id="openai",
            retry_count=int(self.request.retries or 0),
        )


@celery_app.task(
    base=_TranscribeEpisodeTask,
    name="app.workers.tasks.transcribe_episode",
    bind=True,
    autoretry_for=TRANSIENT_ERRORS,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    priority=9,
)
def transcribe_episode(self, episode_id: str) -> dict:
    # task-failure-monitoring-and-circuit-breaker task 5.1: 若 openai
    # circuit 已 open，self.retry(300s) 把 task 退回 broker 等恢復。
    check_circuit_or_retry(self, "openai")

    # celery-routing-and-dispatcher-fix: 進場第一件事就 idempotency claim。
    # `_claim_queue_row` 是單一短交易（< 50ms，無外部 I/O）：用
    # SELECT FOR UPDATE 撈該 row，依 status / started_at 決定行為。
    claim, queue_row_id = asyncio.run(
        _claim_queue_row(episode_id, self.request.id)
    )
    if claim == CLAIM_NOT_FOUND:
        logger.error(
            "transcribe_episode: queue row for %s 不存在", episode_id
        )
        return {"status": "not_found", "episode_id": episode_id}
    if claim == CLAIM_SKIP_DUPLICATE:
        logger.warning(
            "transcribe_episode: duplicate task for episode %s — acking",
            episode_id,
        )
        return {"status": "duplicate", "episode_id": episode_id}
    if claim == CLAIM_SKIP_TERMINAL:
        logger.info(
            "transcribe_episode: queue row for %s in terminal state — acking",
            episode_id,
        )
        return {"status": "skipped_terminal", "episode_id": episode_id}

    # claim == CLAIM_PROCEED → row 已 set status=running、started_at=NOW、
    # celery_task_id=this id、dispatched_at=NULL
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


async def _claim_queue_row(
    episode_id: str, task_id: str
) -> tuple[str, str | None]:
    """Idempotent worker entry — transitions queue row to running atomically.

    celery-routing-and-dispatcher-fix: dispatcher 不再 set status=running，
    這裡是唯一的 pending→running transition 點。用 SELECT FOR UPDATE 鎖
    該 row、依現況決定 4 種行為：

    1. ``status='pending'`` → set running + started_at + celery_task_id +
       dispatched_at=NULL；回 (CLAIM_PROCEED, row_id)
    2. ``status='running' AND started_at > NOW - 5min`` → 視為重複 task；
       回 (CLAIM_SKIP_DUPLICATE, row_id)。caller 直接 ack 不重跑（防 broker
       redeliver 或 dispatcher 漏網之魚 → 重跑會燒掉 OpenAI ~$1）。
    3. ``status='running' AND started_at <= NOW - 5min`` → stale，原 task
       crash 沒釋放；reclaim：set started_at=NOW + 新 celery_task_id +
       dispatched_at=NULL。回 (CLAIM_PROCEED, row_id) + warning log。
    4. ``status in (completed, failed, cancelled, ignored)`` → 回
       (CLAIM_SKIP_TERMINAL, row_id)，caller 直接 ack。

    Row 不存在回 (CLAIM_NOT_FOUND, None)。

    交易 < 50ms、無外部 I/O。
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
                return CLAIM_NOT_FOUND, None

            now = datetime.now(timezone.utc)
            row_id = str(row.id)

            # Terminal / excluded states — ack and skip.
            if row.status in (
                QueueStatus.cancelled,
                QueueStatus.completed,
                QueueStatus.failed,
            ) or row.ignored:
                return CLAIM_SKIP_TERMINAL, row_id

            if row.status == QueueStatus.running:
                started = row.started_at
                # started_at 可能是 naive；保險 normalize 成 aware UTC
                if started is not None and started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if started is not None:
                    age = (now - started).total_seconds()
                    if age < WORKER_ENTRY_DUPLICATE_WINDOW_SECONDS:
                        logger.warning(
                            "claim: duplicate within %ds — existing task=%s "
                            "incoming task=%s row=%s",
                            WORKER_ENTRY_DUPLICATE_WINDOW_SECONDS,
                            row.celery_task_id,
                            task_id,
                            row_id,
                        )
                        return CLAIM_SKIP_DUPLICATE, row_id
                # Stale (or NULL started_at) → reclaim.
                logger.warning(
                    "claim: reclaiming stale running row %s "
                    "(previous celery_task_id=%s, started_at=%s, "
                    "new task=%s)",
                    row_id,
                    row.celery_task_id,
                    row.started_at,
                    task_id,
                )

            # pending OR stale-running → set running.
            row.status = QueueStatus.running
            row.started_at = now
            row.celery_task_id = task_id
            row.dispatched_at = None
            await session.commit()
            return CLAIM_PROCEED, row_id
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
            # celery-routing-and-dispatcher-fix: terminal transition 也清掉
            # dispatcher 的 memo pad，未來 retry/重新 enqueue 才能再被選。
            row.dispatched_at = None
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
            correction_show_id = episode.show_id

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
                # asr-llm-homophone-postprocess (EQ2b) — FIRST LAYER: LLM
                # homophone detection over the whole episode. Returns word-level
                # {wrong, correct} pairs that are (a) applied to THIS episode
                # immediately (D2, no approval needed) and (b) persisted as
                # pending candidates for cross-episode use after admin review.
                # Both detection and persistence are fail-open: a failure here
                # must never block transcription — it falls back to dictionary-
                # only correction.
                llm_pairs = await asr_homophone.detect_homophones(
                    session, result.text, show_id=correction_show_id
                )
                if llm_pairs:
                    # Persist candidates in a SEPARATE session so its commit
                    # cannot entangle (or prematurely flush) this transaction's
                    # in-flight segment/chunk deletes — the two paths are
                    # independent (D2). Fail-open: persistence failure must not
                    # block the current episode's correction.
                    try:
                        async with Session() as cand_session:
                            await asr_homophone.persist_candidates(
                                cand_session,
                                llm_pairs,
                                show_id=correction_show_id,
                            )
                    except Exception:
                        logger.warning(
                            "asr_homophone: persist_candidates failed for %s; "
                            "current episode still corrected, candidates skipped",
                            episode_id,
                            exc_info=True,
                        )

                # asr-correction-dictionary (EQ2a) — SECOND LAYER: correct known
                # ASR typos from the approved dictionary at the source — before
                # writing segments and building chunks — so the displayed
                # transcript AND the search index carry the fix.
                # fail-open: a correction-load failure must not block the
                # transcription itself; it can be backfilled later.
                try:
                    correction_rules = await asr_correction.load_rules(
                        session, correction_show_id
                    )
                except Exception:
                    logger.warning(
                        "asr_correction: load_rules failed for %s; "
                        "transcribing without correction",
                        episode_id,
                        exc_info=True,
                    )
                    correction_rules = []

                segment_rows: list[TranscriptSegment] = []
                for seg in result.segments:
                    # First layer (LLM pairs) then second layer (dictionary).
                    corrected = asr_correction.apply_corrections(
                        seg.text, llm_pairs
                    )
                    corrected = asr_correction.apply_corrections(
                        corrected, correction_rules
                    )
                    row = TranscriptSegment(
                        transcript_id=transcript_id,
                        start_time=seg.start,
                        end_time=seg.end,
                        text=corrected,
                        # EQ2d F1: snapshot the raw ASR text when a correction
                        # changes it, so the episode stays reversible.
                        original_text=(
                            seg.text if corrected != seg.text else None
                        ),
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
                    corrected_content = asr_correction.apply_corrections(
                        asr_correction.apply_corrections(result.text, llm_pairs),
                        correction_rules,
                    )
                    # EQ2d F1: snapshot the raw ASR full text when correction
                    # changes it, so the episode stays reversible.
                    if (
                        corrected_content != result.text
                        and t.original_content is None
                    ):
                        t.original_content = result.text
                    t.content = corrected_content
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
            # task-failure-monitoring-and-circuit-breaker task 3.3:
            # 不走 self.retry → on_failure 不會 fire → 這裡顯式寫 log。
            # exception 已被 swallow（caller return 正常 dict），但保險起見
            # 仍 mark 防 base on_failure 在某些 corner case 重複寫。
            try:
                setattr(exc, "_failure_logged", True)
            except Exception:
                pass
            record_task_failure(
                task_name="app.workers.tasks.transcribe_episode",
                args=(episode_id,),
                exc=exc,
                provider_id="openai",
                retry_count=int(self.request.retries or 0),
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


@celery_app.task(name="app.workers.tasks.backfill_asr_corrections", bind=True)
def backfill_asr_corrections(
    self, show_id: str | None = None, term_id: str | None = None
) -> dict:
    """Apply ASR correction rules to existing transcripts and recompute the
    affected chunks (text + dual embeddings + tsvector).

    Scope: a single show (`show_id`), a single rule (`term_id`), or all shows
    (neither). Enqueued by the admin backfill endpoint's non-dry-run path. The
    heavy lifting (resumable per-transcript commit, per-chunk fail isolation,
    idempotency) lives in `asr_correction.backfill_corrections`.

    EQ2e F8: `bind=True` so the apply job reports `update_state(PROGRESS, ...)`
    per processed transcript with the unified `{current,total,phase,
    failed_chunk_ids}` meta shape, queryable via the backfill-status endpoint
    and cancellable via revoke.
    """

    def _progress(current: int, total: int, failed_chunk_ids: list[str]) -> None:
        self.update_state(
            state="PROGRESS",
            meta={
                "current": current,
                "total": total,
                "phase": "apply",
                "failed_chunk_ids": failed_chunk_ids,
            },
        )

    return asyncio.run(_run_asr_backfill(show_id, term_id, _progress))


async def _run_asr_backfill(
    show_id: str | None,
    term_id: str | None,
    progress_cb: "asr_correction.ApplyProgressCb | None" = None,
) -> dict:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as session:
            embedding_cfg = await get_step_config(session, "embedding")
            report = await asr_correction.backfill_corrections(
                session,
                show_id=uuid.UUID(show_id) if show_id else None,
                term_id=uuid.UUID(term_id) if term_id else None,
                dry_run=False,
                embedding_cfg=embedding_cfg,
                progress_cb=progress_cb,
            )
        return {
            "status": "completed",
            "affected_transcripts": report.affected_transcripts,
            "affected_segments": report.affected_segments,
            "affected_chunks": report.affected_chunks,
            "failed_chunk_ids": report.failed_chunk_ids,
        }
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.tasks.detect_existing_episodes", bind=True)
def detect_existing_episodes(self, show_id: str) -> dict:
    """EQ2e F6: run homophone DETECTION over every existing transcript of a
    show, producing pending candidates only — it NEVER changes transcript text.

    `bind=True` so it reports `update_state(PROGRESS, ...)` per processed episode
    with the unified `{current,total,phase,failed_chunk_ids}` shape (here
    `failed_chunk_ids` carries failed EPISODE ids — the accumulated-failures
    slot), queryable via the backfill-status endpoint and cancellable via
    revoke. The batch driver (sequential, per-episode fail-open) lives in
    `asr_detection_backfill.run_detection_backfill`.
    """

    def _progress(current: int, total: int, failed_episode_ids: list[str]) -> None:
        self.update_state(
            state="PROGRESS",
            meta={
                "current": current,
                "total": total,
                "phase": "detect",
                "failed_chunk_ids": failed_episode_ids,
            },
        )

    return asyncio.run(_run_detect_existing(show_id, _progress))


async def _run_detect_existing(show_id: str, progress_cb) -> dict:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as session:
            report = await asr_detection_backfill.run_detection_backfill(
                session, uuid.UUID(show_id), progress_cb=progress_cb
            )
        return {
            "status": "completed",
            "processed": report["processed"],
            "total": report["total"],
            "persisted": report["persisted"],
            "failed_episode_ids": report["failed_episode_ids"],
        }
    finally:
        await engine.dispose()
