"""Celery broadcast task: reload jieba custom dictionary in every consumer.

`broadcast_reload.delay()` enqueues the task; with multiple Celery workers
each running their own task should call `tokenizer.reload_dictionary` to
pick up the latest DB rows.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services import tokenizer
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tokenizer_reload.broadcast_reload")
def broadcast_reload() -> int:
    return asyncio.run(_reload())


async def _reload() -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as session:
            n = await tokenizer.reload_dictionary(session)
            logger.info("tokenizer dictionary reloaded: %d terms", n)
            return n
    finally:
        await engine.dispose()
