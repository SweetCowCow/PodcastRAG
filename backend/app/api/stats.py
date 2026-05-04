"""Public + admin stats endpoints.

`/stats` is public — used by ReleaseLogPage and PresentationPage to show
total indexed numbers to anonymous visitors. Excludes user count to avoid
leaking how small the userbase is.

`/admin/stats` keeps the full admin view including users count.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_chunk import TranscriptChunk
from app.models.user import User
from app.schemas.stats import PublicStatsResponse, StatsResponse

# Public stats router — no auth required.
public_router = APIRouter(tags=["stats"])


@public_router.get("/stats", response_model=PublicStatsResponse)
async def public_stats(db: AsyncSession = Depends(get_db)) -> PublicStatsResponse:
    episodes_completed = await db.scalar(
        select(func.count())
        .select_from(Transcript)
        .where(Transcript.status == TranscriptStatus.completed)
    )
    transcript_chunks = await db.scalar(
        select(func.count()).select_from(TranscriptChunk)
    )
    shows = await db.scalar(select(func.count()).select_from(Show))
    return PublicStatsResponse(
        episodes_completed=int(episodes_completed or 0),
        transcript_chunks=int(transcript_chunks or 0),
        shows=int(shows or 0),
    )


# Admin stats router — full view including user count.
router = APIRouter(
    prefix="/admin",
    tags=["admin-stats"],
    dependencies=[Depends(require_admin)],
)


@router.get("/stats", response_model=StatsResponse)
async def admin_stats(db: AsyncSession = Depends(get_db)) -> StatsResponse:
    episodes_completed = await db.scalar(
        select(func.count())
        .select_from(Transcript)
        .where(Transcript.status == TranscriptStatus.completed)
    )
    transcript_chunks = await db.scalar(
        select(func.count()).select_from(TranscriptChunk)
    )
    shows = await db.scalar(select(func.count()).select_from(Show))
    users = await db.scalar(select(func.count()).select_from(User))
    return StatsResponse(
        episodes_completed=int(episodes_completed or 0),
        transcript_chunks=int(transcript_chunks or 0),
        shows=int(shows or 0),
        users=int(users or 0),
    )
