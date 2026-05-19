"""Framework-agnostic ToolContext: DI for real services.

The LLM never sees this — it's passed by the framework adapter as the
second argument to every tool call (Pydantic AI: RunContext.deps;
OpenAI native: kwarg; ADK: session state).
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Callable

import redis
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ToolContext:
    show_id: uuid.UUID
    session_id: str
    db_factory: Callable[[], AsyncSession]
    redis_client: redis.Redis

    @classmethod
    def from_env(
        cls, show_id: uuid.UUID, session_id: str
    ) -> "ToolContext":
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        # Use the canonical app Redis (= celery broker). Falls back to REDIS_URL
        # env if settings doesn't expose celery_broker_url (e.g. local pytest).
        redis_url = (
            getattr(settings, "celery_broker_url", None)
            or os.environ.get("REDIS_URL")
            or "redis://localhost:6379/0"
        )
        rc = redis.Redis.from_url(redis_url, decode_responses=True)
        return cls(
            show_id=show_id,
            session_id=session_id,
            db_factory=Session,
            redis_client=rc,
        )
