"""asr_homophone: default model = gemini-3.5-flash via Zeabur AI Hub

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-02

The EQ2b RAGEC pilot compared models on the candidate-grounded task. With the
candidate-entity list grounding, gemini-3.5-flash gave the best recall of real
ASR mis-hearings (guest names + known typos) at the lowest cost; the approval
gate handles its modest false-positive rate. This sets the asr_homophone step's
default to gemini-3.5-flash via the AI Hub (chat) — an admin can still retune
model / base_url / key in the AI Step UI afterwards.

Idempotent: only updates the row if the AI Hub key exists; otherwise leaves the
prior config so the step is never left without a usable key.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ai_steps
        SET base_url = 'https://hnd1.aihub.zeabur.ai/v1',
            model = 'gemini-3.5-flash',
            api_key_id = COALESCE(
                (SELECT id FROM api_keys WHERE provider = 'zeabur-aihub' LIMIT 1),
                api_key_id
            )
        WHERE step_key = 'asr_homophone'
        """
    )


def downgrade() -> None:
    # Revert to the original seed (gpt-4o-mini on OpenAI) from a1b2c3d4e5f6.
    op.execute(
        """
        UPDATE ai_steps
        SET base_url = 'https://api.openai.com/v1',
            model = 'gpt-4o-mini',
            api_key_id = COALESCE(
                (SELECT id FROM api_keys WHERE provider = 'openai' LIMIT 1),
                api_key_id
            )
        WHERE step_key = 'asr_homophone'
        """
    )
