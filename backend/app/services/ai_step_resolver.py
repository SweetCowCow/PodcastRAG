"""Resolve runtime LLM / embedding / whisper endpoint configuration from
the `ai_steps` table (joined with `api_keys`). Replaces the old
`services.llm_config` module that read from the singleton `llm_config` table
and `settings.openai_api_key`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_step import AiStep, StepKey, StepType
from app.models.api_key import ApiKey


class AiStepNotConfiguredError(RuntimeError):
    """Raised when a caller asks for a step that exists but lacks required
    settings (most commonly api_key_id)."""


@dataclass(frozen=True)
class StepConfig:
    step_key: str
    step_type: str
    base_url: str | None
    api_key: str | None
    model: str | None
    extra_config: dict[str, Any]


_STEP_TYPES_REQUIRING_API_KEY = {StepType.chat.value, StepType.embedding.value}


async def get_step_config(db: AsyncSession, step_key: str) -> StepConfig:
    """Look up `step_key` in `ai_steps`, join `api_keys`, validate, return
    a frozen StepConfig.

    Raises AiStepNotConfiguredError if the row exists but lacks the api_key
    that this step_type needs (chat / embedding always need a key; whisper
    only needs one when extra_config.provider == 'openai').
    """
    if step_key not in {k.value for k in StepKey}:
        raise AiStepNotConfiguredError(f"unknown step_key: {step_key}")

    step = await db.get(AiStep, step_key)
    if step is None:
        raise AiStepNotConfiguredError(
            f"ai_steps.{step_key} row missing; run alembic migration"
        )

    api_key_value: str | None = None
    if step.api_key_id is not None:
        ak = await db.get(ApiKey, step.api_key_id)
        if ak is None:
            raise AiStepNotConfiguredError(
                f"ai_steps.{step_key} references missing api_key_id"
            )
        api_key_value = ak.api_key

    extra = step.extra_config or {}
    needs_key = step.step_type in _STEP_TYPES_REQUIRING_API_KEY or (
        step.step_type == StepType.whisper.value
        and extra.get("provider") == "openai"
    )
    if needs_key and not api_key_value:
        raise AiStepNotConfiguredError(
            f"ai_steps.{step_key} requires an api_key — set it in admin"
        )

    needs_base_url = step.step_type in _STEP_TYPES_REQUIRING_API_KEY or (
        step.step_type == StepType.whisper.value
        and extra.get("provider") == "openai"
    )
    if needs_base_url and not step.base_url:
        raise AiStepNotConfiguredError(
            f"ai_steps.{step_key} requires base_url — set it in admin"
        )

    if not step.model and step.step_type != StepType.whisper.value:
        # whisper-local can technically run with empty model name (defaults
        # internally) but chat/embedding always need a model selected.
        raise AiStepNotConfiguredError(
            f"ai_steps.{step_key} requires model — set it in admin"
        )

    return StepConfig(
        step_key=step.step_key,
        step_type=step.step_type,
        base_url=step.base_url,
        api_key=api_key_value,
        model=step.model,
        extra_config=dict(extra),
    )


def infer_provider_label(base_url: str | None) -> str:
    """User-facing provider label for error messages. Inlined from the
    deprecated services.llm_config module."""
    if not base_url:
        return "OpenAI"
    try:
        host = urlparse(base_url).hostname or ""
    except (ValueError, AttributeError):
        return "External API"
    if not host:
        return "External API"
    if host.endswith("openai.com"):
        return "OpenAI"
    if "zeabur" in host:
        return "Zeabur AI Hub"
    return host
