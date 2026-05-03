"""Admin endpoints for AI summary regeneration and backfill."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.episode import AiSummaryStatus, Episode
from app.models.transcript import Transcript, TranscriptStatus

router = APIRouter(prefix="/episodes", tags=["admin", "episode-summary"])


class RegenerateResponse(BaseModel):
    episode_id: uuid.UUID
    enqueued: bool


class BackfillResponse(BaseModel):
    enqueued_count: int


@router.post(
    "/{episode_id}/regenerate-summary", response_model=RegenerateResponse
)
async def regenerate_summary(
    episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> RegenerateResponse:
    ep = await db.get(Episode, episode_id)
    if ep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Episode 不存在"
        )

    ep.ai_summary_status = AiSummaryStatus.pending.value
    await db.commit()

    # Late import to avoid celery_app import at module load time in environments
    # without a broker (test collection).
    from app.workers.summary_task import generate_episode_summary

    generate_episode_summary.delay(str(episode_id))
    return RegenerateResponse(episode_id=episode_id, enqueued=True)


@router.post("/backfill-summary", response_model=BackfillResponse)
async def backfill_summary(db: AsyncSession = Depends(get_db)) -> BackfillResponse:
    """Enqueue summary task for every transcribed episode that has no summary.

    Idempotent: re-running picks up only rows still missing a summary; rows
    already in-flight (status='running') re-enter via short-circuit and exit
    without re-doing the LLM work.
    """
    rows = (
        await db.execute(
            select(Episode.id)
            .join(Transcript, Transcript.episode_id == Episode.id)
            .where(
                and_(
                    Episode.ai_summary.is_(None),
                    Transcript.status == TranscriptStatus.completed,
                )
            )
        )
    ).scalars().all()

    from app.workers.summary_task import generate_episode_summary

    for ep_id in rows:
        generate_episode_summary.delay(str(ep_id))

    return BackfillResponse(enqueued_count=len(rows))
