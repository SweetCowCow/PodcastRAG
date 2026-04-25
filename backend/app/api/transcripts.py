import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.episode import Episode
from app.models.show import Show
from app.models.show_schedule import ShowSchedule
from app.models.transcript import Transcript, TranscriptStatus
from app.schemas.sync import SyncResponse, TranscribeLatestResponse
from app.schemas.transcript import (
    BatchTranscribeResponse,
    TranscriptQueuedResponse,
    TranscriptResponse,
    TranscriptSegmentResponse,
)
from app.services.rss_parser import RssParseError
from app.services.sync import sync_show_episodes
from app.workers.dispatch import enqueue_transcription

router = APIRouter(tags=["transcripts"])


@router.post(
    "/episodes/{episode_id}/transcribe",
    response_model=TranscriptQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def transcribe_episode(
    episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> TranscriptQueuedResponse:
    episode = await db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode 不存在")

    transcript = (
        await db.execute(select(Transcript).where(Transcript.episode_id == episode_id))
    ).scalar_one_or_none()

    if transcript and transcript.status == TranscriptStatus.processing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="該集數正在轉錄中",
        )

    if transcript is None:
        transcript = Transcript(episode_id=episode_id, status=TranscriptStatus.pending)
        db.add(transcript)
    else:
        transcript.status = TranscriptStatus.pending
        transcript.error_message = None

    await db.flush()
    enqueue_transcription(episode_id)
    queued_at = datetime.now(timezone.utc)

    return TranscriptQueuedResponse(
        transcript_id=transcript.id,
        status=transcript.status.value,
        queued_at=queued_at,
    )


@router.get(
    "/episodes/{episode_id}/transcript",
    response_model=TranscriptResponse,
)
async def get_transcript(
    episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> TranscriptResponse:
    transcript = (
        await db.execute(
            select(Transcript)
            .options(selectinload(Transcript.segments))
            .where(Transcript.episode_id == episode_id)
        )
    ).scalar_one_or_none()

    if transcript is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚無轉錄")

    segments = sorted(transcript.segments, key=lambda s: s.start_time)
    return TranscriptResponse(
        id=transcript.id,
        episode_id=transcript.episode_id,
        status=transcript.status.value,
        language=transcript.language,
        transcribed_at=transcript.transcribed_at,
        error_message=transcript.error_message,
        segments=[TranscriptSegmentResponse.model_validate(s) for s in segments],
    )


@router.post(
    "/shows/{show_id}/transcribe-all",
    response_model=BatchTranscribeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def transcribe_show(
    show_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> BatchTranscribeResponse:
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    episodes = (
        await db.execute(
            select(Episode)
            .options(selectinload(Episode.transcript))
            .where(Episode.show_id == show_id)
        )
    ).scalars().all()

    queued = 0
    for ep in episodes:
        transcript = ep.transcript
        if transcript and transcript.status in (
            TranscriptStatus.completed,
            TranscriptStatus.processing,
            TranscriptStatus.pending,
        ):
            continue

        if transcript is None:
            transcript = Transcript(
                episode_id=ep.id, status=TranscriptStatus.pending
            )
            db.add(transcript)
        else:
            transcript.status = TranscriptStatus.pending
            transcript.error_message = None

        await db.flush()
        enqueue_transcription(ep.id)
        queued += 1

    return BatchTranscribeResponse(queued=queued)


@router.post(
    "/shows/{show_id}/transcribe-latest",
    response_model=TranscribeLatestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def transcribe_latest(
    show_id: uuid.UUID,
    max_episodes: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> TranscribeLatestResponse:
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    try:
        synced = await sync_show_episodes(show_id, db)
    except RssParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if max_episodes is not None and max_episodes > 0:
        effective_max = max_episodes
    else:
        schedule = (
            await db.execute(
                select(ShowSchedule).where(ShowSchedule.show_id == show_id)
            )
        ).scalar_one_or_none()
        if schedule and schedule.max_episodes > 0:
            effective_max = schedule.max_episodes
        else:
            effective_max = 5

    candidates = (
        await db.execute(
            select(Episode)
            .options(selectinload(Episode.transcript))
            .where(Episode.show_id == show_id)
            .order_by(Episode.published_at.desc())
        )
    ).scalars().all()

    queued = 0
    for ep in candidates:
        if queued >= effective_max:
            break
        transcript = ep.transcript
        if transcript and transcript.status == TranscriptStatus.completed:
            continue

        if transcript is None:
            transcript = Transcript(
                episode_id=ep.id, status=TranscriptStatus.pending
            )
            db.add(transcript)
        else:
            transcript.status = TranscriptStatus.pending
            transcript.error_message = None

        await db.flush()
        enqueue_transcription(ep.id)
        queued += 1

    return TranscribeLatestResponse(
        queued=queued,
        synced=SyncResponse(**synced),
    )
