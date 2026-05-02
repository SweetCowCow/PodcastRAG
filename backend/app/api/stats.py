"""Admin stats endpoint for the public Release Log page banner."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_chunk import TranscriptChunk
from app.models.user import User
from app.schemas.stats import StatsResponse

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
