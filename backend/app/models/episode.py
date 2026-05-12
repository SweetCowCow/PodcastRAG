import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AiSummaryStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("show_id", "guid", name="uq_episode_show_guid"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    show_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shows.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    guid: Mapped[str] = mapped_column(String(2048), nullable=False)
    audio_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary_status: Mapped[str] = mapped_column(
        Enum(
            AiSummaryStatus,
            name="ai_summary_status_enum",
            values_callable=lambda x: [m.value for m in x],
            create_type=False,
        ),
        nullable=False,
        server_default=AiSummaryStatus.pending.value,
    )
    ai_summary_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ai_summary_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_summary_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ai_summary_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    show: Mapped["Show"] = relationship(back_populates="episodes")
    transcript: Mapped["Transcript | None"] = relationship(back_populates="episode")
    description_chunks: Mapped[list["EpisodeDescriptionChunk"]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
    )
