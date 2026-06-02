import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TranscriptStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status: Mapped[TranscriptStatus] = mapped_column(
        Enum(TranscriptStatus), nullable=False, default=TranscriptStatus.pending
    )
    language: Mapped[str | None] = mapped_column(nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # asr-correction-reversibility-and-content-sync (EQ2d F1): the pre-correction
    # full-episode text, captured once when the transcript is first corrected
    # (never overwritten). NULL = never corrected, or restored.
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    episode: Mapped["Episode"] = relationship(back_populates="transcript")
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["TranscriptChunk"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )
