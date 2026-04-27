import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.schemas.queue import QueueListOut, QueueRowOut

router = APIRouter(prefix="/admin/queue", tags=["queue"])


@router.get("", response_model=QueueListOut)
async def list_queue(db: AsyncSession = Depends(get_db)) -> QueueListOut:
    rows = (
        await db.scalars(
            select(TranscriptionQueue).order_by(
                TranscriptionQueue.position.asc(),
                TranscriptionQueue.enqueued_at.desc(),
            )
        )
    ).all()

    grouped: dict[QueueStatus, list[QueueRowOut]] = {
        QueueStatus.pending: [],
        QueueStatus.running: [],
        QueueStatus.completed: [],
        QueueStatus.failed: [],
        QueueStatus.cancelled: [],
    }
    for row in rows:
        grouped[row.status].append(QueueRowOut.model_validate(row))

    for key in (
        QueueStatus.running,
        QueueStatus.completed,
        QueueStatus.failed,
        QueueStatus.cancelled,
    ):
        grouped[key].sort(key=lambda r: r.enqueued_at, reverse=True)

    return QueueListOut(
        pending=grouped[QueueStatus.pending],
        running=grouped[QueueStatus.running],
        completed=grouped[QueueStatus.completed],
        failed=grouped[QueueStatus.failed],
        cancelled=grouped[QueueStatus.cancelled],
    )


@router.post("/{queue_id}/cancel", response_model=QueueRowOut)
async def cancel_queue_row(
    queue_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> QueueRowOut:
    row = await db.get(TranscriptionQueue, queue_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Queue row 不存在"
        )
    if row.status != QueueStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"無法取消 status={row.status.value} 的 queue row："
                "只有 pending 可被取消"
            ),
        )
    row.status = QueueStatus.cancelled
    await db.flush()
    await db.refresh(row)
    return QueueRowOut.model_validate(row)


@router.post("/{queue_id}/ignore", response_model=QueueRowOut)
async def ignore_queue_row(
    queue_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> QueueRowOut:
    row = await db.get(TranscriptionQueue, queue_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Queue row 不存在"
        )
    row.ignored = True
    await db.flush()
    await db.refresh(row)
    return QueueRowOut.model_validate(row)


@router.post("/{queue_id}/unignore", response_model=QueueRowOut)
async def unignore_queue_row(
    queue_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> QueueRowOut:
    row = await db.get(TranscriptionQueue, queue_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Queue row 不存在"
        )
    row.ignored = False
    await db.flush()
    await db.refresh(row)
    return QueueRowOut.model_validate(row)
