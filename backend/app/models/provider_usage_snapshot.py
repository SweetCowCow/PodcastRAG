"""ORM models for the multi-provider usage monitoring change.

Two tables:

- ``provider_usage_snapshot``: per-provider per-model per-day spend totals.
  Generic schema so new providers (deepgram, anthropic-direct, …) can be
  added by inserting rows without an alembic migration.

- ``usage_alert_log``: per-day per-provider per-severity dedupe so the
  daily threshold alert beat task only sends one yellow + one red email per
  provider per day.
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProviderUsageSnapshot(Base):
    """One row per ``(provider, model, date)`` — re-fetching overwrites.

    The ``model`` column is nullable because some providers expose only
    aggregate daily spend (no per-model breakdown). The unique constraint
    treats ``NULL`` model as "the aggregate row for that provider+date".
    Postgres treats ``NULL`` as distinct in unique constraints by default,
    so we add an explicit ``COALESCE`` partial in the migration. The model
    here uses the simple ``UniqueConstraint``; the migration adds the
    coalesce variant.
    """

    __tablename__ = "provider_usage_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "provider", "model", "date", name="uq_provider_usage_snapshot_pmd"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    date: Mapped[_date] = mapped_column(Date, nullable=False)
    spend_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UsageAlertLog(Base):
    """Dedupe table for daily threshold alerts.

    PK = (provider, severity, alerted_date) — the alert beat task checks
    for an existing row before sending and inserts after successful send.
    """

    __tablename__ = "usage_alert_log"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), primary_key=True)
    alerted_date: Mapped[_date] = mapped_column(Date, primary_key=True)
    alerted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
