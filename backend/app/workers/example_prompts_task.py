"""Celery task: generate per-mode guiding example prompts for one show.

Part of change `per-show-mode-example-prompts`. Wraps the fail-open
`services.example_prompts.generate_for_show`. Chained off the summary pipeline
(once a show's episode summaries all finish) and runnable via admin backfill.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.episode import AiSummaryStatus, Episode
from app.services.example_prompts import generate_for_show
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def maybe_enqueue_for_show(db, show_id) -> bool:
    """Enqueue example-prompt generation iff the show has no episode summary
    still pending/running (i.e. this was the last one to finish).

    Returns True if a task was enqueued. Idempotency of generation itself is
    handled downstream by `generate_for_show` (delete-then-insert per mode), so
    an occasional double-enqueue is harmless.
    """
    remaining = await db.scalar(
        select(func.count())
        .select_from(Episode)
        .where(
            Episode.show_id == show_id,
            Episode.ai_summary_status.in_(
                [AiSummaryStatus.pending.value, AiSummaryStatus.running.value]
            ),
        )
    )
    if remaining and remaining > 0:
        return False
    generate_show_example_prompts.delay(str(show_id))
    logger.info("example_prompts: enqueued generation for show %s", show_id)
    return True


@celery_app.task(
    name="app.workers.example_prompts_task.generate_show_example_prompts",
    bind=True,
    priority=2,
)
def generate_show_example_prompts(self, show_id: str) -> dict:
    return asyncio.run(_run(show_id))


async def _run(show_id: str) -> dict:
    sid = uuid.UUID(show_id)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            counts = await generate_for_show(db, sid)
        logger.info("example_prompts: show %s generated %s", show_id, counts)
        return {"ok": True, "counts": counts}
    finally:
        await engine.dispose()
