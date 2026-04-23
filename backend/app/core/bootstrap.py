import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.models.llm_config import LlmConfig

logger = logging.getLogger(__name__)


async def seed_llm_config_from_env() -> None:
    """Populate llm_config api_key fields from ZEABUR_API_KEY when empty.

    Runs on backend startup. Idempotent: only overwrites empty fields.
    Admin UI updates remain authoritative — once the DB has a value, we
    never overwrite it from env.
    """
    key = settings.zeabur_api_key
    if not key:
        return

    async with AsyncSessionFactory() as session:
        cfg = (
            await session.execute(select(LlmConfig).where(LlmConfig.id == 1))
        ).scalar_one_or_none()
        if cfg is None:
            return

        changed: list[str] = []
        if not cfg.answer_api_key:
            cfg.answer_api_key = key
            changed.append("answer_api_key")
        if not cfg.rewrite_api_key:
            cfg.rewrite_api_key = key
            changed.append("rewrite_api_key")

        if changed:
            cfg.updated_at = datetime.now(timezone.utc)
            await session.commit()
            logger.info("llm_config seeded from ZEABUR_API_KEY: %s", ",".join(changed))
