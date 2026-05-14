"""Admin endpoints for inspecting and editing per-episode guest lists.

- GET  /admin/episodes/{episode_id}/guests   → single episode snapshot
- PUT  /admin/episodes/{episode_id}/guests   → replace list (full overwrite)
- GET  /admin/shows/{show_id}/guests          → list every episode in a show
                                                 sorted by published_at DESC

Auth: the parent admin router already mounts `require_admin` as a
dependency, so non-admins receive 403 before any handler runs.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.episode import Episode
from app.models.show import Show
from app.schemas.episode_guests import EpisodeGuestsOut, EpisodeGuestsUpdate

router = APIRouter(tags=["admin", "episode-guests"])


@router.get(
    "/episodes/{episode_id}/guests",
    response_model=EpisodeGuestsOut,
)
async def get_episode_guests(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EpisodeGuestsOut:
    ep = await db.get(Episode, episode_id)
    if ep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"episode {episode_id} not found",
        )
    return EpisodeGuestsOut.model_validate(ep)


@router.put(
    "/episodes/{episode_id}/guests",
    response_model=EpisodeGuestsOut,
)
async def update_episode_guests(
    episode_id: uuid.UUID,
    body: EpisodeGuestsUpdate,
    db: AsyncSession = Depends(get_db),
) -> EpisodeGuestsOut:
    ep = await db.get(Episode, episode_id)
    if ep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"episode {episode_id} not found",
        )

    await db.execute(
        update(Episode).where(Episode.id == episode_id).values(guests=body.guests)
    )
    await db.commit()
    await db.refresh(ep)
    return EpisodeGuestsOut.model_validate(ep)


@router.get(
    "/shows/{show_id}/guests",
    response_model=list[EpisodeGuestsOut],
)
async def list_show_episode_guests(
    show_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[EpisodeGuestsOut]:
    """List every episode in `show_id` with its current guests, newest first."""
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"show {show_id} not found",
        )

    rows = (
        await db.execute(
            select(Episode)
            .where(Episode.show_id == show_id)
            .order_by(Episode.published_at.desc().nullslast())
        )
    ).scalars().all()
    return [EpisodeGuestsOut.model_validate(ep) for ep in rows]
