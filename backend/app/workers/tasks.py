import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_chunk import TranscriptChunk
from app.models.transcript_segment import TranscriptSegment
from app.services import storage
from app.services.chunking import build_chunks
from app.services.embedding import embed_texts
from app.services.transcription import get_provider
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX_LEN = 2000


@celery_app.task(name="app.workers.tasks.transcribe_episode", bind=True)
def transcribe_episode(self, episode_id: str) -> dict:
    return asyncio.run(_run(episode_id))


async def _run(episode_id: str) -> dict:
    ep_uuid = uuid.UUID(episode_id)
    temp_audio_path: str | None = None

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as session:
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

            provider = get_provider()
            result = await provider.transcribe(temp_audio_path, language=show_language)

            async with Session() as session:
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
                embeddings = (
                    await asyncio.to_thread(
                        embed_texts, [c.text for c in chunk_drafts]
                    )
                    if chunk_drafts
                    else []
                )
                for idx, (draft, vector) in enumerate(zip(chunk_drafts, embeddings)):
                    session.add(
                        TranscriptChunk(
                            transcript_id=transcript_id,
                            chunk_index=idx,
                            start_time=draft.start_time,
                            end_time=draft.end_time,
                            text=draft.text,
                            embedding=vector,
                            segment_ids=draft.segment_ids,
                        )
                    )

                t = await session.get(Transcript, transcript_id)
                if t is not None:
                    t.status = TranscriptStatus.completed
                    t.language = result.language or show_language
                    t.content = result.text
                    t.error_message = None
                    t.transcribed_at = datetime.now(timezone.utc)
                await session.commit()

            return {
                "status": "completed",
                "episode_id": episode_id,
                "segments": len(result.segments),
                "chunks": len(chunk_drafts),
            }

        except Exception as exc:
            logger.exception("transcribe_episode 失敗 episode=%s", episode_id)
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
