"""add source/status to asr_correction_terms

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-06-02

Part of change `asr-llm-homophone-postprocess` (EQ2b). Adds provenance and an
approval lifecycle to the ASR correction dictionary so LLM-detected homophone
pairs can be persisted as pending candidates without affecting resolution:

- `source` (text, default 'manual'): 'manual' (EQ2a admin rules) | 'llm'
- `status` (text, default 'approved'): 'pending' | 'approved' | 'rejected'

Existing rows are backfilled to source='manual', status='approved' so EQ2a
behaviour is unchanged (every pre-existing rule keeps resolving exactly as
before). The server_default carries the same values for any code path that
inserts without specifying them.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asr_correction_terms",
        sa.Column(
            "source",
            sa.String(length=10),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "asr_correction_terms",
        sa.Column(
            "status",
            sa.String(length=10),
            nullable=False,
            server_default="approved",
        ),
    )
    # Backfill is implicit via server_default for existing rows, but set it
    # explicitly too so the intent is unambiguous and resilient to any
    # default-evaluation edge case.
    op.execute(
        "UPDATE asr_correction_terms "
        "SET source = 'manual', status = 'approved' "
        "WHERE source IS NULL OR status IS NULL"
    )


def downgrade() -> None:
    op.drop_column("asr_correction_terms", "status")
    op.drop_column("asr_correction_terms", "source")
