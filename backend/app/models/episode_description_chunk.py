import uuid
from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EpisodeDescriptionChunk(Base):
    __tablename__ = "episode_description_chunks"
    __table_args__ = (
        UniqueConstraint(
            "episode_id",
            "chunking_version",
            "chunk_index",
            name="uq_desc_chunk_episode_version_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunking_version: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=sa.text("1"),
        default=1,
    )
    chunk_index: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=sa.text("0"),
        default=0,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_tsvector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    episode: Mapped["Episode"] = relationship(back_populates="description_chunks")
