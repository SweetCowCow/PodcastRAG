"""add provider_usage_snapshot and usage_alert_log tables

Revision ID: x2e3f4a5b6c7
Revises: w1d2e3f4a5b6
Create Date: 2026-05-17

Tables are idempotent (IF NOT EXISTS guarded) so re-running on a partially-
upgraded environment is safe. The unique constraint on
``provider_usage_snapshot`` uses ``COALESCE(model, '')`` so two rows with
NULL model + same (provider, date) still collide (Postgres' default NULL-
distinct behaviour would otherwise allow duplicates of aggregate rows).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "x2e3f4a5b6c7"
down_revision: str | None = "w1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "provider_usage_snapshot" not in existing_tables:
        op.create_table(
            "provider_usage_snapshot",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("model", sa.String(length=128), nullable=True),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("spend_usd", sa.Numeric(10, 4), nullable=False),
            sa.Column(
                "raw_payload",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "fetched_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        # COALESCE-based unique index so NULL model is treated as ''
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_provider_usage_snapshot_pmd "
            "ON provider_usage_snapshot "
            "(provider, COALESCE(model, ''), date)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_provider_usage_snapshot_provider_date "
            "ON provider_usage_snapshot (provider, date DESC)"
        )

    if "usage_alert_log" not in existing_tables:
        op.create_table(
            "usage_alert_log",
            sa.Column("provider", sa.String(length=64), primary_key=True),
            sa.Column("severity", sa.String(length=16), primary_key=True),
            sa.Column("alerted_date", sa.Date(), primary_key=True),
            sa.Column(
                "alerted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_provider_usage_snapshot_provider_date")
    op.execute("DROP INDEX IF EXISTS uq_provider_usage_snapshot_pmd")
    op.execute("DROP TABLE IF EXISTS provider_usage_snapshot")
    op.execute("DROP TABLE IF EXISTS usage_alert_log")
