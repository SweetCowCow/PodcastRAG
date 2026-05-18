"""task_failure_log model — persisted Celery task failure events.

Part of `task-failure-monitoring-and-circuit-breaker` change. Every Celery
task's `on_failure` (or permanent-error short-circuit path) writes one row.
The failure-alert beat task aggregates over a 30-min sliding window.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FailureType(str, enum.Enum):
    permanent = "permanent"
    transient = "transient"
    unknown = "unknown"


class TaskFailureLog(Base):
    __tablename__ = "task_failure_log"
    __table_args__ = (
        Index("ix_task_failure_log_failed_at", "failed_at"),
        Index(
            "ix_task_failure_log_task_failed_at",
            "task_name",
            "failed_at",
        ),
        Index(
            "ix_task_failure_log_provider_failed_at",
            "provider_id",
            "failed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_args_json: Mapped[dict | list | None] = mapped_column(
        JSONB, nullable=True
    )
    failure_type: Mapped[str] = mapped_column(
        Enum(
            FailureType,
            name="task_failure_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    error_class: Mapped[str] = mapped_column(String(255), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
