"""add api_keys and ai_steps tables, migrate from llm_config + env

Revision ID: l0a1b2c3d4e5
Revises: k9f0a1b2c3d4
Create Date: 2026-05-03

This is Rev A of the admin-llm-step-config split. It does NOT drop llm_config —
that happens in a later Rev B once application code stops reading the old table.
"""
from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "l0a1b2c3d4e5"
down_revision: str | None = "k9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Provider inference from base_url host. Anything else falls into "unknown".
def _infer_provider(base_url: str | None) -> str:
    if not base_url:
        return "unknown"
    host = (urlparse(base_url).hostname or "").lower()
    if "aihub.zeabur" in host:
        return "zeabur-aihub"
    if "api.openai.com" in host or host == "openai.com":
        return "openai"
    return "unknown"


def upgrade() -> None:
    # ── 1. Create api_keys ──
    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "provider", "label", name="uq_api_keys_provider_label"
        ),
    )

    # ── 2. Create ai_steps ──
    op.create_table(
        "ai_steps",
        sa.Column("step_key", sa.String(50), primary_key=True),
        sa.Column("step_type", sa.String(20), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "extra_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "step_key IN ('answer', 'rewrite', 'summary', 'embedding', 'transcription')",
            name="ck_ai_steps_step_key",
        ),
        sa.CheckConstraint(
            "step_type IN ('chat', 'embedding', 'whisper')",
            name="ck_ai_steps_step_type",
        ),
    )

    # ── 3. Pre-insert 5 hardcoded step rows ──
    bind = op.get_bind()
    api_keys_t = sa.table(
        "api_keys",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("provider", sa.String),
        sa.column("label", sa.String),
        sa.column("api_key", sa.Text),
    )
    ai_steps_t = sa.table(
        "ai_steps",
        sa.column("step_key", sa.String),
        sa.column("step_type", sa.String),
        sa.column("base_url", sa.String),
        sa.column("model", sa.String),
        sa.column("api_key_id", postgresql.UUID(as_uuid=True)),
        sa.column("extra_config", postgresql.JSONB),
    )

    op.bulk_insert(
        ai_steps_t,
        [
            {"step_key": "answer", "step_type": "chat", "extra_config": {}},
            {"step_key": "rewrite", "step_type": "chat", "extra_config": {}},
            {"step_key": "summary", "step_type": "chat", "extra_config": {}},
            {"step_key": "embedding", "step_type": "embedding", "extra_config": {}},
            {
                "step_key": "transcription",
                "step_type": "whisper",
                "extra_config": {},
            },
        ],
    )

    # ── 4. Import legacy llm_config (Rev A task 2.2) ──
    # api_keys for (answer_api_key, answer_base_url) and (rewrite_api_key,
    # rewrite_base_url) inferred providers; deduplicated by raw key value so
    # the same key is not inserted twice across answer + rewrite.
    legacy = bind.execute(
        sa.text(
            "SELECT answer_base_url, answer_api_key, answer_model, "
            "rewrite_base_url, rewrite_api_key, rewrite_model "
            "FROM llm_config WHERE id = 1"
        )
    ).fetchone()

    # key (raw api_key) -> api_key_id
    inserted_keys: dict[str, uuid.UUID] = {}

    def _ensure_key(raw_key: str, provider: str, label: str) -> uuid.UUID:
        if raw_key in inserted_keys:
            return inserted_keys[raw_key]
        # Avoid colliding on (provider, label) UNIQUE if multiple raw keys share them.
        # Caller guarantees label is unique per insertion site.
        new_id = uuid.uuid4()
        op.bulk_insert(
            api_keys_t,
            [
                {
                    "id": new_id,
                    "provider": provider,
                    "label": label,
                    "api_key": raw_key,
                }
            ],
        )
        inserted_keys[raw_key] = new_id
        return new_id

    if legacy is not None:
        ans_provider = _infer_provider(legacy.answer_base_url)
        rw_provider = _infer_provider(legacy.rewrite_base_url)
        ans_kid = _ensure_key(
            legacy.answer_api_key, ans_provider, "legacy-answer"
        )
        # rewrite key may equal answer key; _ensure_key dedups. If providers
        # differ but key string is identical, the first-seen provider wins
        # (acceptable: real-world they'll match because the same Hub key serves
        # both answer + rewrite).
        if legacy.rewrite_api_key == legacy.answer_api_key:
            rw_kid = ans_kid
        else:
            rw_kid = _ensure_key(
                legacy.rewrite_api_key, rw_provider, "legacy-rewrite"
            )

        bind.execute(
            sa.text(
                "UPDATE ai_steps SET base_url=:b, model=:m, api_key_id=:k "
                "WHERE step_key='answer'"
            ),
            {
                "b": legacy.answer_base_url,
                "m": legacy.answer_model,
                "k": str(ans_kid),
            },
        )
        bind.execute(
            sa.text(
                "UPDATE ai_steps SET base_url=:b, model=:m, api_key_id=:k "
                "WHERE step_key='rewrite'"
            ),
            {
                "b": legacy.rewrite_base_url,
                "m": legacy.rewrite_model,
                "k": str(rw_kid),
            },
        )

    # ── 5. Import OPENAI_API_KEY env (Rev A task 2.3) ──
    openai_env_key = os.environ.get("OPENAI_API_KEY")
    openai_kid: uuid.UUID | None = None
    if openai_env_key:
        if openai_env_key in inserted_keys:
            openai_kid = inserted_keys[openai_env_key]
        else:
            openai_kid = _ensure_key(
                openai_env_key, "openai", "legacy-env-import"
            )
        # Wire embedding step. Default to text-embedding-3-small + OpenAI base.
        bind.execute(
            sa.text(
                "UPDATE ai_steps SET base_url=:b, model=:m, api_key_id=:k "
                "WHERE step_key='embedding'"
            ),
            {
                "b": "https://api.openai.com/v1",
                "m": "text-embedding-3-small",
                "k": str(openai_kid),
            },
        )

    # ── 6. Import transcription settings (Rev A task 2.4) ──
    transcription_provider = os.environ.get(
        "TRANSCRIPTION_PROVIDER", "openai"
    ).strip().lower()
    if transcription_provider == "openai":
        # OpenAI Whisper API. Reuse the openai key inserted above if present.
        extra = {"provider": "openai"}
        bind.execute(
            sa.text(
                "UPDATE ai_steps SET base_url=:b, model=:m, api_key_id=:k, "
                "extra_config = CAST(:e AS jsonb) "
                "WHERE step_key='transcription'"
            ),
            {
                "b": "https://api.openai.com/v1",
                "m": "whisper-1",
                "k": str(openai_kid) if openai_kid else None,
                "e": json.dumps(extra),
            },
        )
    elif transcription_provider == "faster-whisper":
        # Local model — no api_key, no base_url.
        extra = {
            "provider": "faster-whisper",
            "model_dir": os.environ.get(
                "FASTER_WHISPER_MODEL_DIR", "/models/faster-whisper"
            ),
        }
        bind.execute(
            sa.text(
                "UPDATE ai_steps SET base_url=NULL, model=:m, api_key_id=NULL, "
                "extra_config = CAST(:e AS jsonb) "
                "WHERE step_key='transcription'"
            ),
            {
                "m": os.environ.get("FASTER_WHISPER_MODEL_SIZE", "base"),
                "e": json.dumps(extra),
            },
        )
    # Other / unknown providers leave transcription step blank for admin to fill.


def downgrade() -> None:
    op.drop_table("ai_steps")
    op.drop_table("api_keys")
