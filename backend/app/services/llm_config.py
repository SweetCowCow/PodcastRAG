from datetime import datetime, timezone
from urllib.parse import urlparse

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_config import LlmConfig


class LLMNotConfigured(RuntimeError):
    """Raised when chat-mode is invoked but answer/rewrite api_key is empty."""


_ALLOWED_FIELDS = {
    "answer_base_url",
    "answer_api_key",
    "answer_model",
    "rewrite_base_url",
    "rewrite_api_key",
    "rewrite_model",
}


async def get_config(db: AsyncSession) -> LlmConfig:
    cfg = (await db.execute(select(LlmConfig).where(LlmConfig.id == 1))).scalar_one_or_none()
    if cfg is None:
        raise LLMNotConfigured("llm_config row missing; run the migration")
    return cfg


def require_keys_present(cfg: LlmConfig) -> None:
    if not cfg.answer_api_key or not cfg.rewrite_api_key:
        raise LLMNotConfigured(
            "LLM is not configured: fill in both answer_api_key and rewrite_api_key"
        )


async def update_config(db: AsyncSession, updates: dict) -> LlmConfig:
    cfg = await get_config(db)
    for key, value in updates.items():
        if key not in _ALLOWED_FIELDS:
            continue
        if value is None:
            continue
        setattr(cfg, key, value)
    cfg.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return cfg


def get_answer_client(cfg: LlmConfig) -> tuple[OpenAI, str]:
    client = OpenAI(base_url=cfg.answer_base_url, api_key=cfg.answer_api_key)
    return client, cfg.answer_model


def get_rewrite_client(cfg: LlmConfig) -> tuple[OpenAI, str]:
    client = OpenAI(base_url=cfg.rewrite_base_url, api_key=cfg.rewrite_api_key)
    return client, cfg.rewrite_model


def infer_provider_label(base_url: str | None) -> str:
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
