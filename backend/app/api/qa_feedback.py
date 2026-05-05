"""QA feedback endpoints — thumbs up/down + admin stats.

R1.1 first-mile: gather direct user signals (vote + optional comment) on AI
answers. Append-only model so re-votes preserve history; aggregation reads
the latest row per (user_id, query_id).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin, require_authenticated_user
from app.models.qa_feedback import QAFeedback
from app.models.user import User
from app.schemas.qa_feedback import (
    QAFeedbackCreate,
    QAFeedbackOut,
    QAFeedbackStats,
)

router = APIRouter(prefix="/qa-feedback", tags=["qa-feedback"])


@router.post("", response_model=QAFeedbackOut, status_code=201)
async def submit_qa_feedback(
    payload: QAFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
) -> QAFeedback:
    row = QAFeedback(
        query_id=payload.query_id,
        user_id=user.id,
        vote=payload.vote,
        comment=payload.comment,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/stats", response_model=QAFeedbackStats)
async def qa_feedback_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> QAFeedbackStats:
    """Return up/down/ratio over the last rolling 7 days, counting only the
    LATEST vote per (user_id, query_id) so re-votes don't double count."""
    since = datetime.now(timezone.utc) - timedelta(days=7)

    # Subquery: latest created_at per (user_id, query_id) within window.
    latest_per_pair = (
        select(
            QAFeedback.user_id.label("user_id"),
            QAFeedback.query_id.label("query_id"),
            func.max(QAFeedback.created_at).label("latest_at"),
        )
        .where(QAFeedback.created_at >= since)
        .group_by(QAFeedback.user_id, QAFeedback.query_id)
        .subquery()
    )

    # Join back to read the vote at the latest timestamp.
    stmt = select(QAFeedback.vote, func.count().label("c")).join(
        latest_per_pair,
        (QAFeedback.user_id == latest_per_pair.c.user_id)
        & (QAFeedback.query_id == latest_per_pair.c.query_id)
        & (QAFeedback.created_at == latest_per_pair.c.latest_at),
    ).group_by(QAFeedback.vote)

    rows = (await db.execute(stmt)).all()
    counts = {vote: int(c) for vote, c in rows}
    up = counts.get("up", 0)
    down = counts.get("down", 0)
    total = up + down
    ratio = round(up / total, 2) if total > 0 else None
    return QAFeedbackStats(up_7d=up, down_7d=down, total_7d=total, ratio=ratio)
