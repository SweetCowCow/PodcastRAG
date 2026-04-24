import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcript import Transcript
from app.schemas.episode import EpisodeResponse

router = APIRouter(tags=["episodes"])


@router.get("/shows/{show_id}/episodes", response_model=list[EpisodeResponse])
async def list_episodes(
    show_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    show = await db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    stmt = (
        select(Episode, Transcript.status.label("transcript_status"))
        .outerjoin(Transcript, Transcript.episode_id == Episode.id)
        .where(Episode.show_id == show_id)
        .order_by(Episode.published_at.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    rows = result.all()

    episodes = []
    for episode, ts in rows:
        data = EpisodeResponse.model_validate(episode)
        data.transcript_status = ts.value if ts is not None else None
        episodes.append(data)
    return episodes
