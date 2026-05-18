"""add task_failure_log + service_circuit_state tables

Revision ID: a5b6c7d8e9f0
Revises: z4a5b6c7d8e9
Create Date: 2026-05-18

Part of `task-failure-monitoring-and-circuit-breaker`. Adds:

- ``task_failure_log``: persisted per-task failure events. Every
  Celery ``Task.on_failure`` (or permanent-error short-circuit) writes
  one row. The failure-alert beat task aggregates over a 30-min sliding
  window; a daily cleanup task deletes rows older than 30 days.
- ``service_circuit_state``: one row per known external provider
  (openai / aihub / zsend). Atomic UPDATE-WHERE-state-RETURNING is used
  to make open/close transitions race-safe across worker / beat / admin
  contention.

Two PG ENUMs are introduced:

- ``task_failure_type`` (permanent | transient | unknown)
- ``service_circuit_state_enum`` (closed | open)
- ``service_circuit_probe_result_enum`` (success | failure)

Provider rows are NOT seeded here — the backend startup hook is
responsible (see ``task-failure-monitoring-and-circuit-breaker`` task 1.2).
This keeps the migration pure-DDL and idempotent for fresh / upgrade
environments alike.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a5b6c7d8e9f0"
down_revision: str | None = "z4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FAILURE_TYPE_ENUM = "task_failure_type"
CIRCUIT_STATE_ENUM = "service_circuit_state_enum"
PROBE_RESULT_ENUM = "service_circuit_probe_result_enum"


def upgrade() -> None:
    failure_type = sa.Enum(
        "permanent", "transient", "unknown", name=FAILURE_TYPE_ENUM
    )
    circuit_state = sa.Enum("closed", "open", name=CIRCUIT_STATE_ENUM)
    probe_result = sa.Enum("success", "failure", name=PROBE_RESULT_ENUM)

    failure_type.create(op.get_bind(), checkfirst=True)
    circuit_state.create(op.get_bind(), checkfirst=True)
    probe_result.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "task_failure_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("task_name", sa.String(255), nullable=False),
        sa.Column("task_args_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "failure_type",
            postgresql.ENUM(name=FAILURE_TYPE_ENUM, create_type=False),
            nullable=False,
        ),
        sa.Column("error_class", sa.String(255), nullable=False),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column("provider_id", sa.String(32), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_task_failure_log_failed_at",
        "task_failure_log",
        ["failed_at"],
    )
    op.create_index(
        "ix_task_failure_log_task_failed_at",
        "task_failure_log",
        ["task_name", "failed_at"],
    )
    op.create_index(
        "ix_task_failure_log_provider_failed_at",
        "task_failure_log",
        ["provider_id", "failed_at"],
    )

    op.create_table(
        "service_circuit_state",
        sa.Column("provider_id", sa.String(32), primary_key=True),
        sa.Column("task_type", sa.String(64), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(name=CIRCUIT_STATE_ENUM, create_type=False),
            nullable=False,
            server_default="closed",
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "paused_task_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_probe_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_probe_result",
            postgresql.ENUM(name=PROBE_RESULT_ENUM, create_type=False),
            nullable=True,
        ),
        sa.Column(
            "manual_resumed_by", sa.String(255), nullable=True
        ),
        sa.Column(
            "manual_resumed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_table("service_circuit_state")
    op.drop_index(
        "ix_task_failure_log_provider_failed_at",
        table_name="task_failure_log",
    )
    op.drop_index(
        "ix_task_failure_log_task_failed_at",
        table_name="task_failure_log",
    )
    op.drop_index(
        "ix_task_failure_log_failed_at", table_name="task_failure_log"
    )
    op.drop_table("task_failure_log")

    bind = op.get_bind()
    sa.Enum(name=PROBE_RESULT_ENUM).drop(bind, checkfirst=True)
    sa.Enum(name=CIRCUIT_STATE_ENUM).drop(bind, checkfirst=True)
    sa.Enum(name=FAILURE_TYPE_ENUM).drop(bind, checkfirst=True)
