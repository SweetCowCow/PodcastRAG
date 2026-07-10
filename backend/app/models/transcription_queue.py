import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QueueStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TranscriptionQueue(Base):
    __tablename__ = "transcription_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    show_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shows.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[QueueStatus] = mapped_column(
        Enum(QueueStatus, name="queue_status"),
        nullable=False,
        default=QueueStatus.pending,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ignored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    whisper_model: Mapped[str] = mapped_column(String(50), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # celery-routing-and-dispatcher-fix: dispatcher 自己的 memo pad；
    # SELECT 排除 dispatched_at IS NOT NULL 防同 row 連發兩 task。
    # worker entry + terminal transition 都會清回 NULL。
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # worker-reliability D2: orphan-revert 每復活一次 +1，滿門檻標 terminal
    # failed；手動 retry 與成功完成歸零。
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
