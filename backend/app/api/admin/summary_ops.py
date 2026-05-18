"""Admin endpoints for AI summary regeneration and backfill."""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from kombu.exceptions import OperationalError as KombuOperationalError
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.episode import AiSummaryStatus, Episode
from app.models.transcript import Transcript, TranscriptStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/episodes", tags=["admin", "episode-summary"])

# celery-publish-routing-fix-and-f2-smoke: 把 publish-side silent drop
# 轉成 loud 503。原 .delay() 因為 task_publish_retry=True + retry policy
# max_retries=3 會把 broker 短暫斷線吞成 silent OK；對「按按鈕就要看到
# 結果」的 admin foreground path，寧可讓 user 立刻看到 503 重按，也不要
# 回 200 enqueued=true 卻沒人收到 task。
#
# 背景任務（dispatcher 推 transcribe / topic）仍然走預設 retry path，
# 由 worker autoretry / circuit breaker 兜底。


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

    try:
        # retry=False → broker 連不上或 publish 失敗時直接 raise，不吞成
        # silent OK。OperationalError 是 kombu 對 broker 層異常的 wrapper。
        generate_episode_summary.apply_async(
            args=[str(episode_id)], retry=False
        )
    except (KombuOperationalError, ConnectionError, OSError) as exc:
        logger.exception(
            "summary regenerate publish failed for episode %s", episode_id
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任務派送失敗（broker 不可用），請稍後再試",
        ) from exc
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

    enqueued = 0
    for ep_id in rows:
        try:
            generate_episode_summary.apply_async(
                args=[str(ep_id)], retry=False
            )
            enqueued += 1
        except (KombuOperationalError, ConnectionError, OSError) as exc:
            # backfill 是批次任務，broker 中途斷線就提早結束回報已派幾筆，
            # 而不是吞 silent → 讓 admin 知道部分 enqueue 失敗。
            logger.exception(
                "summary backfill publish failed at episode %s (enqueued=%d before fail)",
                ep_id,
                enqueued,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"任務派送失敗（broker 不可用），已成功派送 {enqueued} 筆",
            ) from exc

    return BackfillResponse(enqueued_count=enqueued)
