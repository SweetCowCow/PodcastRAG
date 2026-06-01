import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AsrCorrectionTerm(Base):
    """ASR 錯字校正規則：``wrong`` → ``correct``，``scope`` 為 ``global`` 或 ``show``。

    唯一性以兩個 partial unique index 實作，而非單純複合 ``UNIQUE(wrong, scope,
    show_id)``：Postgres 將 NULL 視為彼此 distinct，複合 unique 無法擋住兩條重複
    的 global 規則（``show_id`` 皆為 NULL）。因此拆成 global 規則 ``wrong`` 唯一、
    show 規則 ``(wrong, show_id)`` 唯一。
    """

    __tablename__ = "asr_correction_terms"
    __table_args__ = (
        Index(
            "uq_asr_correction_global_wrong",
            "wrong",
            unique=True,
            postgresql_where=text("scope = 'global'"),
        ),
        Index(
            "uq_asr_correction_show_wrong",
            "wrong",
            "show_id",
            unique=True,
            postgresql_where=text("scope = 'show'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wrong: Mapped[str] = mapped_column(Text, nullable=False)
    correct: Mapped[str] = mapped_column(Text, nullable=False)
    # 'global' applies to every show; 'show' applies only to the bound show_id.
    scope: Mapped[str] = mapped_column(String(10), nullable=False, default="show")
    show_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shows.id", ondelete="CASCADE"),
        nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
