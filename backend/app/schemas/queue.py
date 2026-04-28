import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.transcription_queue import QueueStatus


class QueueRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    episode_id: uuid.UUID
    show_id: uuid.UUID
    status: QueueStatus
    position: int
    enqueued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    ignored: bool
    whisper_model: str
    celery_task_id: str | None = None


class CancelQueueRowOut(QueueRowOut):
    force_cancelled: bool = False


class QueueListOut(BaseModel):
    """Queue rows grouped by status for the admin queue page.

    ``pending`` is sorted by ``position`` ascending (FIFO order);
    other groups are sorted by ``enqueued_at`` descending (newest first).
    """

    pending: list[QueueRowOut]
    running: list[QueueRowOut]
    completed: list[QueueRowOut]
    failed: list[QueueRowOut]
    cancelled: list[QueueRowOut]
