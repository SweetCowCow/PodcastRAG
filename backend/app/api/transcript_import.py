"""Admin endpoint: import an externally produced transcript for one episode.

external-transcript-bulk-import D3: `POST
/admin/episodes/{episode_id}/transcript-import` accepts a whisper
verbose_json-shaped payload (`model` / `language` / `text` /
`segments[].start/end/text`), validates it against the field whitelist, and
enqueues `import_external_transcript` on the control queue. The endpoint
never writes transcript artifacts synchronously — persistence (and its
failure handling) lives entirely in the Celery task.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.episode import Episode
from app.models.transcription_queue import QueueStatus, TranscriptionQueue
from app.workers.import_task import import_external_transcript

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin-transcript-import"],
    dependencies=[Depends(require_admin)],
)


class ImportSegment(BaseModel):
    """One verbose_json segment. Whitelist: extra fields are rejected so a
    malformed exporter fails loudly instead of silently dropping data."""

    model_config = ConfigDict(extra="forbid")

    start: float
    end: float
    text: str

    @field_validator("text")
    @classmethod
    def _text_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("segment text 不可為空")
        return v

    @model_validator(mode="after")
    def _times_valid(self) -> "ImportSegment":
        if self.start < 0:
            raise ValueError("segment start 不可為負")
        if self.start > self.end:
            raise ValueError("segment start 不可大於 end")
        return self


class TranscriptImportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    language: str | None = None
    text: str
    segments: list[ImportSegment]

    @field_validator("text")
    @classmethod
    def _text_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text 不可為空")
        return v

    @field_validator("segments")
    @classmethod
    def _segments_non_empty(
        cls, v: list[ImportSegment]
    ) -> list[ImportSegment]:
        if not v:
            raise ValueError("segments 不可為空")
        return v


class TranscriptImportQueuedResponse(BaseModel):
    task_id: str
    episode_id: uuid.UUID


@router.post(
    "/episodes/{episode_id}/transcript-import",
    response_model=TranscriptImportQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_transcript(
    episode_id: uuid.UUID,
    payload: TranscriptImportPayload,
    db: AsyncSession = Depends(get_db),
) -> TranscriptImportQueuedResponse:
    episode = await db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Episode 不存在"
        )

    queue_row = (
        await db.execute(
            select(TranscriptionQueue).where(
                TranscriptionQueue.episode_id == episode_id
            )
        )
    ).scalar_one_or_none()
    if queue_row is not None and queue_row.status in (
        QueueStatus.pending,
        QueueStatus.running,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="該集數有進行中的轉錄，無法匯入",
        )

    # celery-publish-routing-fix-and-f2-smoke 慣例：retry=False 讓 broker
    # 斷線時 fail loud（500）而不是無限重試假裝成功。
    task = import_external_transcript.apply_async(
        args=[str(episode_id), payload.model_dump()], retry=False
    )
    logger.info(
        "transcript-import queued: episode=%s task=%s model=%s segments=%d",
        episode_id,
        task.id,
        payload.model,
        len(payload.segments),
    )
    return TranscriptImportQueuedResponse(
        task_id=task.id, episode_id=episode_id
    )
