"""add asr_homophone AI step

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-06-02

Part of change `asr-llm-homophone-postprocess` (EQ2b). Registers the
`asr_homophone` chat step used by the first-layer LLM homophone detector.

- Drop + re-create ck_ai_steps_step_key with `asr_homophone` whitelisted.
- INSERT one row: step_key='asr_homophone', step_type='chat',
  model='gpt-4o-mini', base_url=OpenAI, api_key_id auto-resolved to the unique
  openai-provider key (else NULL for admin to set), and extra_config seeded
  with the default detection prompt under the `prompt` key.

The prompt text below is kept identical to
`app.services.asr_homophone.DEFAULT_HOMOPHONE_PROMPT`, which is the fallback the
detector uses if an admin clears extra_config.prompt. Seeding it here makes the
prompt visible and editable in the admin AI Step UI from day one.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEFAULT_PROMPT = (
    "你是中文 podcast 逐字稿的同音字校對員。輸入是一整集的逐字稿。"
    "語音辨識（ASR）常把專有名詞（人名、樂團名、節目術語、地名）聽成同音或近音的錯字。"
    "你的任務：找出這些『同音誤聽』的詞，輸出『錯字 → 正字』的詞級替換清單。\n\n"
    "嚴格規則：\n"
    "1. 只回同音 / 近音誤聽造成的詞級錯字，不要修文法、語氣、標點或句子結構。\n"
    "2. wrong 與 correct 都必須是可以直接做字串取代的詞，且 wrong 必須原樣出現在逐字稿中。\n"
    "3. 保留原本的專名拼寫意圖；不確定是不是錯字就不要回（寧缺勿濫，避免誤改正確專名）。\n"
    "4. 不要回已經正確的詞、一般常用詞、或只是斷詞不同的情況。\n"
    "5. 嚴格只輸出 JSON 陣列，格式為 "
    '[{"wrong": "錯字", "correct": "正字"}]；沒有任何同音錯字時回 []。'
)


def upgrade() -> None:
    op.execute("ALTER TABLE ai_steps DROP CONSTRAINT IF EXISTS ck_ai_steps_step_key")
    op.execute(
        "ALTER TABLE ai_steps ADD CONSTRAINT ck_ai_steps_step_key "
        "CHECK (step_key IN ('answer', 'rewrite', 'summary', 'embedding', "
        "'transcription', 'entity_extraction', 'asr_homophone'))"
    )

    extra_config = json.dumps({"prompt": _DEFAULT_PROMPT}, ensure_ascii=False)
    op.execute(
        sa.text(
            """
            INSERT INTO ai_steps (step_key, step_type, base_url, model, api_key_id, extra_config)
            VALUES (
                'asr_homophone',
                'chat',
                'https://api.openai.com/v1',
                'gpt-4o-mini',
                (
                    SELECT id FROM api_keys
                    WHERE provider = 'openai'
                    LIMIT 1
                ),
                CAST(:extra_config AS jsonb)
            )
            ON CONFLICT (step_key) DO NOTHING
            """
        ).bindparams(extra_config=extra_config)
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_steps WHERE step_key = 'asr_homophone'")
    op.execute("ALTER TABLE ai_steps DROP CONSTRAINT IF EXISTS ck_ai_steps_step_key")
    op.execute(
        "ALTER TABLE ai_steps ADD CONSTRAINT ck_ai_steps_step_key "
        "CHECK (step_key IN ('answer', 'rewrite', 'summary', 'embedding', "
        "'transcription', 'entity_extraction'))"
    )
