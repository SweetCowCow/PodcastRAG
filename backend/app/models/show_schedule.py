import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RefreshStatus(str, enum.Enum):
    never = "never"
    success = "success"
    failed = "failed"


class ShowSchedule(Base):
    __tablename__ = "show_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    show_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shows.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    run_time: Mapped[str] = mapped_column(String(5), nullable=False)
    whisper_model: Mapped[str] = mapped_column(String(50), nullable=False)
    max_episodes_per_run: Mapped[int] = mapped_column(Integer, nullable=False)
    last_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refresh_status: Mapped[RefreshStatus] = mapped_column(
        Enum(RefreshStatus, name="refresh_status"),
        nullable=False,
        default=RefreshStatus.never,
    )
    last_refresh_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
