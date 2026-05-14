import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StepKey(str, enum.Enum):
    answer = "answer"
    rewrite = "rewrite"
    summary = "summary"
    embedding = "embedding"
    transcription = "transcription"
    entity_extraction = "entity_extraction"


class StepType(str, enum.Enum):
    chat = "chat"
    embedding = "embedding"
    whisper = "whisper"


# Fixed mapping of step_key -> step_type. Migration writes these once;
# the API layer never lets clients change step_type after the fact.
STEP_KEY_TO_TYPE: dict[StepKey, StepType] = {
    StepKey.answer: StepType.chat,
    StepKey.rewrite: StepType.chat,
    StepKey.summary: StepType.chat,
    StepKey.embedding: StepType.embedding,
    StepKey.transcription: StepType.whisper,
    StepKey.entity_extraction: StepType.chat,
}


class AiStep(Base):
    __tablename__ = "ai_steps"
    __table_args__ = (
        CheckConstraint(
            "step_key IN ('answer', 'rewrite', 'summary', 'embedding', 'transcription', 'entity_extraction')",
            name="ck_ai_steps_step_key",
        ),
        CheckConstraint(
            "step_type IN ('chat', 'embedding', 'whisper')",
            name="ck_ai_steps_step_type",
        ),
    )

    step_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="RESTRICT"),
        nullable=True,
    )
    extra_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
