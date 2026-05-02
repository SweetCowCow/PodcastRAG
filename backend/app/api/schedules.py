import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.episode import Episode
from app.models.show import Show
from app.models.show_schedule import ShowSchedule
from app.models.transcript import Transcript, TranscriptStatus
from app.schemas.schedule import (
    AdminScheduleItem,
    ScheduleResponse,
    ScheduleUpsert,
)

router = APIRouter(tags=["schedules"], dependencies=[Depends(require_admin)])


SCHEDULE_DEFAULTS = {
    "enabled": False,
    "frequency": "daily",
    "run_time": "06:00",
    "day_of_week": 0,
    "whisper_model": "large-v3",
}


@router.get("/shows/{show_id}/schedule", response_model=ScheduleResponse)
async def get_schedule(show_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    schedule = await db.scalar(
        select(ShowSchedule).where(ShowSchedule.show_id == show_id)
    )
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Schedule 不存在"
        )
    return schedule


@router.put("/shows/{show_id}/schedule", response_model=ScheduleResponse)
async def upsert_schedule(
    show_id: uuid.UUID,
    payload: ScheduleUpsert,
    db: AsyncSession = Depends(get_db),
):
    show = await db.get(Show, show_id)
    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在"
        )

    schedule = await db.scalar(
        select(ShowSchedule).where(ShowSchedule.show_id == show_id)
    )
    provided = payload.model_dump(exclude_unset=True)

    if schedule is None:
        values = {**SCHEDULE_DEFAULTS, **provided}
        schedule = ShowSchedule(show_id=show_id, **values)
        db.add(schedule)
    else:
        for key, value in provided.items():
            setattr(schedule, key, value)

    await db.flush()
    await db.refresh(schedule)
    return schedule


@router.delete(
    "/shows/{show_id}/schedule", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_schedule(
    show_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    schedule = await db.scalar(
        select(ShowSchedule).where(ShowSchedule.show_id == show_id)
    )
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Schedule 不存在"
        )
    await db.delete(schedule)
    return None


@router.get("/admin/schedules", response_model=list[AdminScheduleItem])
async def list_admin_schedules(db: AsyncSession = Depends(get_db)):
    completed_case = case(
        (Transcript.status == TranscriptStatus.completed, 1), else_=None
    )
    completed_updated = case(
        (Transcript.status == TranscriptStatus.completed, Transcript.transcribed_at),
        else_=None,
    )

    stmt = (
        select(
            Show,
            ShowSchedule,
            func.count(Episode.id).label("episode_count"),
            func.count(completed_case).label("completed_count"),
            func.max(completed_updated).label("last_transcribed_at"),
        )
        .outerjoin(ShowSchedule, ShowSchedule.show_id == Show.id)
        .outerjoin(Episode, Episode.show_id == Show.id)
        .outerjoin(Transcript, Transcript.episode_id == Episode.id)
        .group_by(Show.id, ShowSchedule.id)
        .order_by(Show.created_at.desc())
    )

    result = await db.execute(stmt)
    items: list[AdminScheduleItem] = []
    for show, schedule, episode_count, completed_count, last_at in result.all():
        pending_count = max(0, (episode_count or 0) - (completed_count or 0))
        items.append(
            AdminScheduleItem(
                show_id=show.id,
                show_title=show.title,
                rss_url=show.rss_url,
                schedule=(
                    ScheduleResponse.model_validate(schedule) if schedule else None
                ),
                pending_count=pending_count,
                last_transcribed_at=last_at,
            )
        )
    return items
