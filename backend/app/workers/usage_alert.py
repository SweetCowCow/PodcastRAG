"""Daily Beat task: evaluate per-provider monthly spend vs budget.

Runs daily at 09:00 Asia/Taipei (= cron ``0 1 * * *`` UTC). Per provider:

1. Compute current calendar month accumulated spend by summing
   ``provider_usage_snapshot.spend_usd`` where
   ``date_trunc('month', date) = date_trunc('month', NOW())``.
2. Compare against ``settings.provider_budget_usd_monthly[provider]``.
3. Classify severity:
   - ratio >= 0.95 → ``red``
   - ratio >= 0.80 → ``yellow``
   - else no alert
4. Per (provider, severity, UTC alert date) dedupe via ``usage_alert_log``.

The red severity supersedes yellow for the same provider (i.e. if the
provider crossed both thresholds the same day, we send the red email
only — yellow gets no row because the day's "highest severity" is red).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.provider_usage_snapshot import UsageAlertLog
from app.services.zsend import ZSendError, send_usage_threshold_alert
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

YELLOW_THRESHOLD = 0.80
RED_THRESHOLD = 0.95


@celery_app.task(name="app.workers.usage_alert.evaluate_usage_thresholds")
def evaluate_usage_thresholds() -> dict:
    return asyncio.run(_run())


async def _run() -> dict:
    if not settings.zsend_api_key or not settings.zsend_admin_to_email:
        logger.info(
            "usage_alert: ZSend not configured (api_key or admin_to_email missing) "
            "— skipping"
        )
        return {"skipped": "zsend_unconfigured"}

    budgets = settings.provider_budget_usd_monthly
    today_utc = datetime.now(timezone.utc).date()
    # Taipei date for the email header (display only).
    # Asia/Taipei is UTC+8 with no DST; for header display we just shift.
    from datetime import timedelta
    taipei_date = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    summary: dict[str, dict] = {}
    try:
        async with Session() as db:
            for provider, budget in budgets.items():
                if budget <= 0:
                    continue
                accumulated = await _month_to_date_spend(db, provider)
                ratio = float(accumulated) / float(budget) if budget else 0.0
                severity = _classify(ratio)
                summary[provider] = {
                    "accumulated_usd": float(accumulated),
                    "budget_usd": float(budget),
                    "ratio": ratio,
                    "severity": severity,
                }
                if severity is None:
                    continue
                already = await _already_alerted(db, provider, severity, today_utc)
                if already:
                    summary[provider]["skipped"] = "already_alerted"
                    continue
                top_models = await _top_models_for_month(db, provider)
                try:
                    await send_usage_threshold_alert(
                        provider=provider,
                        severity=severity,
                        accumulated_usd=float(accumulated),
                        budget_usd=float(budget),
                        ratio=ratio,
                        top_models=top_models,
                        taipei_date=taipei_date,
                    )
                except ZSendError as exc:
                    if exc.retryable:
                        raise
                    logger.warning(
                        "usage_alert: send failed non-retryably for %s: %s",
                        provider,
                        exc,
                    )
                    continue
                await _record_alert(db, provider, severity, today_utc)
                await db.commit()
                summary[provider]["alerted"] = True
    finally:
        await engine.dispose()

    return summary


def _classify(ratio: float) -> str | None:
    if ratio >= RED_THRESHOLD:
        return "red"
    if ratio >= YELLOW_THRESHOLD:
        return "yellow"
    return None


async def _month_to_date_spend(db: AsyncSession, provider: str) -> Decimal:
    stmt = text(
        """
        SELECT COALESCE(SUM(spend_usd), 0)
        FROM provider_usage_snapshot
        WHERE provider = :provider
          AND date_trunc('month', date) = date_trunc('month', NOW())
        """
    )
    result = await db.execute(stmt, {"provider": provider})
    val = result.scalar()
    return Decimal(str(val or 0))


async def _top_models_for_month(
    db: AsyncSession, provider: str, limit: int = 3
) -> list[tuple[str, float]]:
    stmt = text(
        """
        SELECT COALESCE(model, '(aggregate)') AS model,
               SUM(spend_usd) AS spend
        FROM provider_usage_snapshot
        WHERE provider = :provider
          AND date_trunc('month', date) = date_trunc('month', NOW())
        GROUP BY model
        ORDER BY spend DESC
        LIMIT :lim
        """
    )
    rows = (await db.execute(stmt, {"provider": provider, "lim": limit})).all()
    return [(r[0], float(r[1])) for r in rows]


async def _already_alerted(
    db: AsyncSession, provider: str, severity: str, alerted_date: date
) -> bool:
    """Yellow is suppressed when red has already been sent today (red supersedes).
    Red is independent."""
    if severity == "yellow":
        # Either yellow already sent OR red already sent today → suppress
        stmt = select(UsageAlertLog).where(
            UsageAlertLog.provider == provider,
            UsageAlertLog.alerted_date == alerted_date,
        )
    else:
        stmt = select(UsageAlertLog).where(
            UsageAlertLog.provider == provider,
            UsageAlertLog.severity == severity,
            UsageAlertLog.alerted_date == alerted_date,
        )
    row = (await db.execute(stmt)).first()
    return row is not None


async def _record_alert(
    db: AsyncSession, provider: str, severity: str, alerted_date: date
) -> None:
    stmt = pg_insert(UsageAlertLog).values(
        provider=provider,
        severity=severity,
        alerted_date=alerted_date,
    )
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["provider", "severity", "alerted_date"]
    )
    await db.execute(stmt)
