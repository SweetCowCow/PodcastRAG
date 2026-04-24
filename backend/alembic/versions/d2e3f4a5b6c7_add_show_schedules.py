"""add show_schedules table

Revision ID: d2e3f4a5b6c7
Revises: c1f2d3e4a5b6
Create Date: 2026-04-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1f2d3e4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "show_schedules",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("show_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("frequency", sa.String(length=10), nullable=False),
        sa.Column("run_time", sa.String(length=5), nullable=False),
        sa.Column("whisper_model", sa.String(length=50), nullable=False),
        sa.Column(
            "max_episodes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_show_schedules_show_id",
        "show_schedules",
        "shows",
        ["show_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_show_schedules_show_id",
        "show_schedules",
        ["show_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_show_schedules_show_id", "show_schedules", type_="unique"
    )
    op.drop_constraint(
        "fk_show_schedules_show_id", "show_schedules", type_="foreignkey"
    )
    op.drop_table("show_schedules")
