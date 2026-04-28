import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.schemas.queue import CancelQueueRowOut, QueueListOut, QueueRowOut
from app.workers.celery_app import celery_app
from app.workers.throttle import release_global_slot

logger = logging.getLogger(__name__)

FORCE_CANCEL_MESSAGE = "Force cancelled by admin"

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


@router.post("/{queue_id}/cancel", response_model=CancelQueueRowOut)
async def cancel_queue_row(
    queue_id: uuid.UUID,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> CancelQueueRowOut:
    row = await db.get(TranscriptionQueue, queue_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Queue row 不存在"
        )

    if row.status == QueueStatus.pending:
        row.status = QueueStatus.cancelled
        await db.flush()
        await db.refresh(row)
        return CancelQueueRowOut.model_validate(row)

    if force and row.status == QueueStatus.running:
        task_id = row.celery_task_id
        if task_id:
            try:
                celery_app.control.revoke(
                    task_id, terminate=True, signal="SIGTERM"
                )
            except Exception:
                logger.exception(
                    "force-cancel: revoke failed for task_id=%s queue_id=%s",
                    task_id,
                    queue_id,
                )
            try:
                release_global_slot(task_id)
            except Exception:
                logger.exception(
                    "force-cancel: release_global_slot failed for task_id=%s",
                    task_id,
                )
        row.status = QueueStatus.cancelled
        row.finished_at = datetime.now(timezone.utc)
        row.error_message = FORCE_CANCEL_MESSAGE
        await db.flush()
        await db.refresh(row)
        out = CancelQueueRowOut.model_validate(row)
        out.force_cancelled = True
        return out

    detail = (
        f"無法取消 status={row.status.value} 的 queue row："
        + (
            "只有 pending 可被取消（running 需 force=true）"
            if not force
            else "force=true 僅適用於 running，terminal 狀態不可取消"
        )
    )
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


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
