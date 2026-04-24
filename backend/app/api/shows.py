import asyncio
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus
from app.schemas.show import (
    RssPreviewResponse,
    ShowCreate,
    ShowListItem,
    ShowResponse,
)
from app.schemas.sync import SyncResponse
from app.services.rss_parser import RssParseError, fetch_and_parse

router = APIRouter(prefix="/shows", tags=["shows"])
rss_preview_router = APIRouter(tags=["shows"])


@rss_preview_router.get("/rss-preview", response_model=RssPreviewResponse)
async def rss_preview(url: str = Query(..., description="RSS feed URL")):
    try:
        parsed = await asyncio.wait_for(fetch_and_parse(url), timeout=5.0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="RSS Feed 逾時（5 秒）",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="RSS Feed 逾時（5 秒）",
        )
    except RssParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

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


@router.post("", response_model=ShowResponse, status_code=status.HTTP_201_CREATED)
async def create_show(payload: ShowCreate, db: AsyncSession = Depends(get_db)):
    rss_url = str(payload.rss_url)

    existing = await db.scalar(select(Show).where(Show.rss_url == rss_url))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RSS URL 已註冊",
        )

    try:
        parsed = await fetch_and_parse(rss_url)
    except RssParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

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
            detail="RSS URL 已註冊",
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


@router.delete("/{show_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_show(show_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    show = await db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")
    await db.execute(delete(Show).where(Show.id == show_id))
    return None


@router.post("/{show_id}/sync", response_model=SyncResponse)
async def sync_show(show_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    show = await db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    try:
        parsed = await fetch_and_parse(show.rss_url)
    except RssParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    existing_rows = (
        await db.execute(select(Episode).where(Episode.show_id == show_id))
    ).scalars().all()
    existing_by_guid: dict[str, Episode] = {ep.guid: ep for ep in existing_rows}

    added = 0
    updated = 0
    for ep in parsed.episodes:
        existing_ep = existing_by_guid.get(ep.guid)
        if existing_ep:
            changed = False
            for field in ("title", "description", "audio_url", "duration_seconds", "published_at"):
                new_value = getattr(ep, field)
                if getattr(existing_ep, field) != new_value:
                    setattr(existing_ep, field, new_value)
                    changed = True
            if changed:
                updated += 1
        else:
            db.add(
                Episode(
                    show_id=show_id,
                    title=ep.title,
                    description=ep.description,
                    audio_url=ep.audio_url,
                    duration_seconds=ep.duration_seconds,
                    published_at=ep.published_at,
                    guid=ep.guid,
                )
            )
            added += 1

    await db.flush()
    total = await db.scalar(
        select(func.count(Episode.id)).where(Episode.show_id == show_id)
    )
    return SyncResponse(added=added, updated=updated, total=total or 0)


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
