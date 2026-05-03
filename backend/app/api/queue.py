import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.schemas.queue import (
    CancelQueueRowOut,
    QueueListOut,
    QueuePositionUpdate,
    QueueRowOut,
)
from app.workers.celery_app import celery_app
from app.workers.throttle import release_global_slot

logger = logging.getLogger(__name__)

FORCE_CANCEL_MESSAGE = "Force cancelled by admin"

router = APIRouter(
    prefix="/admin/queue",
    tags=["queue"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=QueueListOut)
async def list_queue(db: AsyncSession = Depends(get_db)) -> QueueListOut:
    from app.models.episode import Episode
    from app.models.show import Show

    stmt = (
        select(
            TranscriptionQueue,
            Episode.title.label("episode_title"),
            Show.title.label("show_title"),
            Episode.ai_summary_status.label("ai_summary_status"),
        )
        .join(Episode, Episode.id == TranscriptionQueue.episode_id, isouter=True)
        .join(Show, Show.id == TranscriptionQueue.show_id, isouter=True)
        .order_by(
            TranscriptionQueue.position.asc(),
            TranscriptionQueue.enqueued_at.desc(),
        )
    )
    result = (await db.execute(stmt)).all()

    grouped: dict[QueueStatus, list[QueueRowOut]] = {
        QueueStatus.pending: [],
        QueueStatus.running: [],
        QueueStatus.completed: [],
        QueueStatus.failed: [],
        QueueStatus.cancelled: [],
    }
    for queue_row, ep_title, sh_title, ai_status in result:
        out = QueueRowOut.model_validate(queue_row)
        out.episode_title = ep_title
        out.show_title = sh_title
        out.ai_summary_status = ai_status
        grouped[queue_row.status].append(out)

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
            release_global_slot(str(queue_id))
        except Exception:
            logger.exception(
                "force-cancel: release_global_slot failed for queue_id=%s",
                queue_id,
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


@router.patch("/{queue_id}/position", response_model=QueueRowOut)
async def reorder_queue_row(
    queue_id: uuid.UUID,
    body: QueuePositionUpdate,
    db: AsyncSession = Depends(get_db),
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
                f"無法重新排序 status={row.status.value} 的 queue row："
                "只有 pending 可被重排"
            ),
        )

    bounds = (
        await db.execute(
            select(
                func.min(TranscriptionQueue.position),
                func.max(TranscriptionQueue.position),
            ).where(TranscriptionQueue.status == QueueStatus.pending)
        )
    ).one()
    pending_min, pending_max = bounds
    new_pos = max(pending_min, min(pending_max, body.position))
    old_pos = row.position

    if new_pos == old_pos:
        await db.refresh(row)
        return QueueRowOut.model_validate(row)

    if new_pos < old_pos:
        await db.execute(
            update(TranscriptionQueue)
            .where(
                TranscriptionQueue.status == QueueStatus.pending,
                TranscriptionQueue.position >= new_pos,
                TranscriptionQueue.position < old_pos,
                TranscriptionQueue.id != queue_id,
            )
            .values(position=TranscriptionQueue.position + 1)
        )
    else:
        await db.execute(
            update(TranscriptionQueue)
            .where(
                TranscriptionQueue.status == QueueStatus.pending,
                TranscriptionQueue.position > old_pos,
                TranscriptionQueue.position <= new_pos,
                TranscriptionQueue.id != queue_id,
            )
            .values(position=TranscriptionQueue.position - 1)
        )

    row.position = new_pos
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
