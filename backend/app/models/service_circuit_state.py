"""service_circuit_state model — per-provider circuit breaker state.

Part of `task-failure-monitoring-and-circuit-breaker` change. One row per
known external provider (`openai`, `aihub`, `zsend`). State transitions are
done with row-level locks + atomic `UPDATE ... WHERE state=? RETURNING ...`
to make the breaker race-safe across worker / beat / admin contention.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CircuitState(str, enum.Enum):
    closed = "closed"
    open = "open"


class ProbeResult(str, enum.Enum):
    success = "success"
    failure = "failure"


class ServiceCircuitState(Base):
    __tablename__ = "service_circuit_state"

    # NOTE: v1 keeps one row per provider (task_type=NULL). The column is
    # reserved so v2 細粒度 per-task-type 不用 alembic migration.
    provider_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(
        Enum(
            CircuitState,
            name="service_circuit_state_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CircuitState.closed.value,
        server_default=CircuitState.closed.value,
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_task_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_probe_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_probe_result: Mapped[str | None] = mapped_column(
        Enum(
            ProbeResult,
            name="service_circuit_probe_result_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
    )
    manual_resumed_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    manual_resumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
