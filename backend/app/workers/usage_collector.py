"""Hourly Beat task: collect daily usage snapshots from every provider.

Runs at ``cron(minute=0)`` — every hour on the hour. Iterates the
``ADAPTERS`` registry and per-adapter:

1. Calls ``fetch_daily_usage(yesterday_utc, today_utc)`` to cover the cross-
   midnight race (provider APIs are near-realtime but can be a few minutes
   late closing yesterday's bucket).
2. UPSERTs each returned ``UsageSnapshot`` into ``provider_usage_snapshot``
   keyed by ``(provider, COALESCE(model, ''), date)``.

Per-adapter failure isolation: if one adapter raises, the error is logged
with ``exc_info=True`` and the loop continues. The next hourly tick retries
automatically — Celery autoretry is **not** used because the natural beat
cadence is already the retry interval.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.services.provider_usage import ADAPTERS, UsageSnapshot
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.usage_collector.collect_provider_usage")
def collect_provider_usage() -> dict:
    return asyncio.run(_run())


async def _run() -> dict:
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    per_provider_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    try:
        for provider_id, fetch in ADAPTERS.items():
            try:
                snapshots = await fetch(yesterday, today)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "usage_collector: adapter %s failed: %r",
                    provider_id,
                    exc,
                    exc_info=True,
                )
                errors[provider_id] = repr(exc)
                continue
            if not snapshots:
                per_provider_counts[provider_id] = 0
                continue
            async with Session() as db:
                await _upsert_snapshots(db, snapshots)
                await db.commit()
            per_provider_counts[provider_id] = len(snapshots)
            logger.info(
                "usage_collector: %s upserted %d snapshots",
                provider_id,
                len(snapshots),
            )
    finally:
        await engine.dispose()

    return {"counts": per_provider_counts, "errors": errors}


async def _upsert_snapshots(db, snapshots: list[UsageSnapshot]) -> None:
    """Upsert a batch of snapshots. Uses ON CONFLICT against the partial
    unique index on (provider, COALESCE(model, ''), date)."""
    # We use a raw INSERT … ON CONFLICT with COALESCE in the conflict
    # target because SQLAlchemy's ``on_conflict_do_update`` cannot target
    # a partial / expression index by name in this version cleanly.
    stmt = text(
        """
        INSERT INTO provider_usage_snapshot
            (provider, model, date, spend_usd, raw_payload, fetched_at)
        VALUES
            (:provider, :model, :date, :spend, CAST(:raw AS JSONB), NOW())
        ON CONFLICT (provider, COALESCE(model, ''), date)
        DO UPDATE SET
            spend_usd = EXCLUDED.spend_usd,
            raw_payload = EXCLUDED.raw_payload,
            fetched_at = NOW()
        """
    )
    import json

    for snap in snapshots:
        await db.execute(
            stmt,
            {
                "provider": snap.provider,
                "model": snap.model,
                "date": snap.date,
                "spend": snap.spend_usd,
                "raw": json.dumps(snap.raw_payload, default=str),
            },
        )
