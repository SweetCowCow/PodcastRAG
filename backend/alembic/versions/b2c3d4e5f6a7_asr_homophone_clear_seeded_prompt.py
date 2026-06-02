"""asr_homophone: drop the seeded open-ended prompt (RAGEC redesign)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-02

The EQ2b pilot showed the original open-ended "find any homophone typos" prompt
fails on both weak (over-correct) and strong (under-correct) models. The
detection was redesigned to RAGEC: the prompt is now composed in code from
`DEFAULT_HOMOPHONE_INSTRUCTION` plus a per-show candidate-entity list. The
instruction lives in code as the single source of truth; an admin may still
override it via extra_config['prompt'], but the originally-seeded open-ended
text must not linger as a stale override.

This migration removes the 'prompt' key from the asr_homophone step's
extra_config so detection falls back to the code default. Idempotent.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE ai_steps SET extra_config = extra_config - 'prompt' "
        "WHERE step_key = 'asr_homophone'"
    )


def downgrade() -> None:
    # No-op: we don't restore the deprecated open-ended prompt. The code default
    # (DEFAULT_HOMOPHONE_INSTRUCTION) applies when extra_config has no 'prompt'.
    pass
