import asyncio
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.schemas.errors import ErrorCode, ErrorResponse
from app.schemas.show import (
    RssPreviewResponse,
    ShowCreate,
    ShowListItem,
    ShowResponse,
)
from app.schemas.sync import SyncResponse
from app.schemas.transcription_status import (
    CurrentlyProcessingItem,
    RecentFailureItem,
    TranscriptionStatusCounts,
    TranscriptionStatusResponse,
)
from app.services.rss_parser import RssParseError, fetch_and_parse
from app.services.sync import sync_show_episodes

router = APIRouter(prefix="/shows", tags=["shows"])
rss_preview_router = APIRouter(tags=["shows"], dependencies=[Depends(require_admin)])


@rss_preview_router.get("/rss-preview", response_model=RssPreviewResponse)
async def rss_preview(url: str = Query(..., description="RSS feed URL")):
    try:
        parsed = await asyncio.wait_for(fetch_and_parse(url), timeout=5.0)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=ErrorResponse(
                error_code=ErrorCode.RSS_TIMEOUT,
                provider=None,
                detail="RSS feed timed out after 5 seconds",
            ).model_dump(),
        ) from exc
    except RssParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ErrorResponse(
                error_code=ErrorCode.RSS_INVALID,
                provider=None,
                detail=str(exc),
            ).model_dump(),
        ) from exc

    latest_published_at = None
    if parsed.episodes:
        published_list = [
            ep.published_at for ep in parsed.episodes if ep.published_at
        ]
        if published_list:
            latest_published_at = max(published_list).isoformat()

    return RssPreviewResponse(
        title=parsed.show.title,
        episode_count=len(parsed.episodes),
        latest_published_at=latest_published_at,
    )


@router.post(
    "",
    response_model=ShowResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_show(payload: ShowCreate, db: AsyncSession = Depends(get_db)):
    rss_url = str(payload.rss_url)

    existing = await db.scalar(select(Show).where(Show.rss_url == rss_url))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(
                error_code=ErrorCode.SHOW_DUPLICATE_RSS,
                provider=None,
                detail="RSS URL already registered",
            ).model_dump(),
        )

    try:
        parsed = await fetch_and_parse(rss_url)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=ErrorResponse(
                error_code=ErrorCode.RSS_TIMEOUT,
                provider=None,
                detail="RSS feed timed out",
            ).model_dump(),
        ) from exc
    except RssParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ErrorResponse(
                error_code=ErrorCode.RSS_INVALID,
                provider=None,
                detail=str(exc),
            ).model_dump(),
        ) from exc

    show = Show(
        title=parsed.show.title,
        description=parsed.show.description,
        rss_url=rss_url,
        image_url=parsed.show.image_url,
        language=parsed.show.language,
    )
    db.add(show)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(
                error_code=ErrorCode.SHOW_DUPLICATE_RSS,
                provider=None,
                detail="RSS URL already registered",
            ).model_dump(),
        ) from exc

    for ep in parsed.episodes:
        db.add(
            Episode(
                show_id=show.id,
                title=ep.title,
                description=ep.description,
                audio_url=ep.audio_url,
                duration_seconds=ep.duration_seconds,
                published_at=ep.published_at,
                guid=ep.guid,
            )
        )

    await db.flush()
    episode_count = len(parsed.episodes)
    await db.refresh(show)

    return _show_to_response(show, episode_count)


@router.get("", response_model=list[ShowListItem])
async def list_shows(db: AsyncSession = Depends(get_db)):
    transcribed_case = case(
        (Transcript.status == TranscriptStatus.completed, 1), else_=None
    )
    stmt = (
        select(
            Show,
            func.count(Episode.id).label("episode_count"),
            func.count(transcribed_case).label("transcribed_count"),
        )
        .outerjoin(Episode, Episode.show_id == Show.id)
        .outerjoin(Transcript, Transcript.episode_id == Episode.id)
        .group_by(Show.id)
        .order_by(Show.created_at.desc())
    )
    result = await db.execute(stmt)
    return [
        _show_to_response(show, episode_count, transcribed_count)
        for show, episode_count, transcribed_count in result.all()
    ]


@router.get("/{show_id}", response_model=ShowResponse)
async def get_show(show_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    show = await db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    count = await db.scalar(
        select(func.count(Episode.id)).where(Episode.show_id == show_id)
    )
    return _show_to_response(show, count or 0)


@router.delete(
    "/{show_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def delete_show(show_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    show = await db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    await db.execute(
        update(TranscriptionQueue)
        .where(
            TranscriptionQueue.show_id == show_id,
            TranscriptionQueue.status.in_(
                (QueueStatus.pending, QueueStatus.running)
            ),
        )
        .values(status=QueueStatus.cancelled)
    )
    await db.commit()

    await db.execute(delete(Show).where(Show.id == show_id))
    return None


@router.post(
    "/{show_id}/sync",
    response_model=SyncResponse,
    dependencies=[Depends(require_admin)],
)
async def sync_show(show_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    show = await db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    try:
        result = await sync_show_episodes(show_id, db)
    except RssParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return SyncResponse(**result)


@router.get(
    "/{show_id}/transcription-status",
    response_model=TranscriptionStatusResponse,
)
async def get_transcription_status(
    show_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    show = await db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    counts_stmt = (
        select(Transcript.status, func.count(Transcript.id))
        .join(Episode, Episode.id == Transcript.episode_id)
        .where(Episode.show_id == show_id)
        .group_by(Transcript.status)
    )
    counts_rows = (await db.execute(counts_stmt)).all()
    counts = TranscriptionStatusCounts()
    for status_value, n in counts_rows:
        # status_value can be the enum or the str depending on driver path
        key = status_value.value if hasattr(status_value, "value") else str(status_value)
        if hasattr(counts, key):
            setattr(counts, key, int(n))

    processing_stmt = (
        select(Episode.id, Episode.title, Transcript.updated_at)
        .join(Transcript, Transcript.episode_id == Episode.id)
        .where(
            Episode.show_id == show_id,
            Transcript.status == TranscriptStatus.processing,
        )
        .order_by(Transcript.updated_at.asc())
        .limit(10)
    )
    currently_processing = [
        CurrentlyProcessingItem(
            episode_id=eid, episode_title=title, started_at=ts
        )
        for eid, title, ts in (await db.execute(processing_stmt)).all()
    ]

    failures_stmt = (
        select(
            Episode.id,
            Episode.title,
            Transcript.error_message,
            Transcript.updated_at,
        )
        .join(Transcript, Transcript.episode_id == Episode.id)
        .where(
            Episode.show_id == show_id,
            Transcript.status == TranscriptStatus.failed,
        )
        .order_by(Transcript.updated_at.desc())
        .limit(10)
    )
    recent_failures = [
        RecentFailureItem(
            episode_id=eid,
            episode_title=title,
            error_message=(msg or "")[:200],
            error_category=None,
            failed_at=ts,
        )
        for eid, title, msg, ts in (await db.execute(failures_stmt)).all()
    ]

    return TranscriptionStatusResponse(
        counts=counts,
        currently_processing=currently_processing,
        recent_failures=recent_failures,
    )


def _show_to_response(
    show: Show, episode_count: int, transcribed_count: int | None = None
) -> dict:
    data = {
        "id": show.id,
        "title": show.title,
        "description": show.description,
        "rss_url": show.rss_url,
        "image_url": show.image_url,
        "language": show.language,
        "created_at": show.created_at,
        "episode_count": episode_count,
    }
    if transcribed_count is not None:
        data["transcribed_count"] = transcribed_count
    return data
