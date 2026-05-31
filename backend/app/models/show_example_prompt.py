import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExamplePromptMode(str, enum.Enum):
    """The three query modes a guiding example prompt can belong to."""

    index = "index"
    semantic = "semantic"
    chat = "chat"


class ShowExamplePrompt(Base):
    """An LLM-pre-generated guiding example question for one show + one query mode.

    Part of change `per-show-mode-example-prompts`. Rows are written by
    `services.example_prompts.generate_for_show` (idempotent per show+mode:
    old rows deleted then re-inserted) and read by the public GET
    `/shows/{id}/example-prompts` endpoint as a cold-start fallback when a
    show has too few trending queries to drive the chip row.
    """

    __tablename__ = "show_example_prompts"
    __table_args__ = (
        UniqueConstraint(
            "show_id", "mode", "ordinal", name="uq_show_example_prompts_show_mode_ordinal"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    show_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shows.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[ExamplePromptMode] = mapped_column(
        Enum(
            ExamplePromptMode,
            name="example_prompt_mode_enum",
            values_callable=lambda x: [m.value for m in x],
            create_type=False,
        ),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
