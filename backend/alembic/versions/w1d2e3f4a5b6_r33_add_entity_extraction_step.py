"""r3-3 phase 6: add entity_extraction AI step

Revision ID: w1d2e3f4a5b6
Revises: v0c1d2e3f4a5
Create Date: 2026-05-14

R3.3 — Phase 6: LLM query entity extractor as a 6th AI step.

- Drop the existing ck_ai_steps_step_key CHECK constraint
- Re-create it with `entity_extraction` added to the whitelist
- INSERT one row: step_key='entity_extraction', step_type='chat',
  model='gpt-4o-mini', base_url=NULL, api_key_id auto-resolved to the
  unique OpenAI key in api_keys (else NULL)

The api_key_id auto-detect heuristic: pick the only api_keys row whose
`provider = 'openai'`. If there are 0 or 2+ such rows, leave api_key_id
NULL and let admin pick via the AI Step UI. extra_config is empty `{}`;
the entity extractor uses the response_format JSON schema baked into the
service code, not config.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "w1d2e3f4a5b6"
down_revision: str | None = "v0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_steps DROP CONSTRAINT IF EXISTS ck_ai_steps_step_key")
    op.execute(
        "ALTER TABLE ai_steps ADD CONSTRAINT ck_ai_steps_step_key "
        "CHECK (step_key IN ('answer', 'rewrite', 'summary', 'embedding', "
        "'transcription', 'entity_extraction'))"
    )

    # Insert the new step. Auto-resolve api_key_id to the single OpenAI key,
    # otherwise leave NULL for admin to configure.
    op.execute(
        """
        INSERT INTO ai_steps (step_key, step_type, base_url, model, api_key_id, extra_config)
        VALUES (
            'entity_extraction',
            'chat',
            'https://api.openai.com/v1',
            'gpt-4o-mini',
            (
                SELECT id FROM api_keys
                WHERE provider = 'openai'
                LIMIT 1
            ),
            '{}'::jsonb
        )
        ON CONFLICT (step_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_steps WHERE step_key = 'entity_extraction'")
    op.execute("ALTER TABLE ai_steps DROP CONSTRAINT IF EXISTS ck_ai_steps_step_key")
    op.execute(
        "ALTER TABLE ai_steps ADD CONSTRAINT ck_ai_steps_step_key "
        "CHECK (step_key IN ('answer', 'rewrite', 'summary', 'embedding', 'transcription'))"
    )
