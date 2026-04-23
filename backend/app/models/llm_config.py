from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LlmConfig(Base):
    __tablename__ = "llm_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_llm_config_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    answer_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    answer_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    answer_model: Mapped[str] = mapped_column(String(200), nullable=False)
    rewrite_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    rewrite_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    rewrite_model: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
