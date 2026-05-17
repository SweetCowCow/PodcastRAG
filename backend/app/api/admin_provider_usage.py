"""Admin REST: multi-provider usage observability.

Two read-only endpoints behind ``require_admin`` (admin role + valid
session). Frontend converts ISO 8601 UTC dates to Asia/Taipei.

- ``GET /admin/provider-usage/daily?start=&end=``: per-day per-provider per-
  model rows in the requested range. Defaults to last 30 days when params
  omitted.
- ``GET /admin/provider-usage/monthly``: per-provider current-month
  aggregate spend + budget + ratio + top 3 models.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/provider-usage",
    tags=["admin-provider-usage"],
    dependencies=[Depends(require_admin)],
)

_MAX_RANGE_DAYS = 366  # one year — guards against absurd ranges


def _parse_date(s: str | None, fallback: date) -> date:
    if not s:
        return fallback
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "bad_date", "message": str(exc)},
        ) from exc


@router.get("/daily")
async def get_daily_usage(
    start: str | None = Query(None),
    end: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    end_date = _parse_date(end, today)
    start_date = _parse_date(start, today - timedelta(days=29))
    if end_date < start_date:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "bad_range", "message": "end before start"},
        )
    if (end_date - start_date).days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "range_too_large",
                "message": f"range > {_MAX_RANGE_DAYS} days",
            },
        )

    stmt = text(
        """
        SELECT provider, model, date, spend_usd
        FROM provider_usage_snapshot
        WHERE date BETWEEN :start AND :end
        ORDER BY date ASC, provider ASC, model ASC NULLS FIRST
        """
    )
    rows = (await db.execute(stmt, {"start": start_date, "end": end_date})).all()
    return [
        {
            "provider": r[0],
            "model": r[1],
            "date": r[2].isoformat(),
            "spend_usd": float(r[3]),
        }
        for r in rows
    ]


@router.get("/monthly")
async def get_monthly_summary(
    db: AsyncSession = Depends(get_db),
) -> dict[str, dict[str, Any]]:
    """Per-provider current month spend + budget + top 3 models."""
    budgets = settings.provider_budget_usd_monthly
    result: dict[str, dict[str, Any]] = {}

    sum_stmt = text(
        """
        SELECT COALESCE(SUM(spend_usd), 0)
        FROM provider_usage_snapshot
        WHERE provider = :provider
          AND date_trunc('month', date) = date_trunc('month', NOW())
        """
    )
    top_stmt = text(
        """
        SELECT COALESCE(model, '(aggregate)'), SUM(spend_usd)
        FROM provider_usage_snapshot
        WHERE provider = :provider
          AND date_trunc('month', date) = date_trunc('month', NOW())
        GROUP BY model
        ORDER BY SUM(spend_usd) DESC
        LIMIT 3
        """
    )

    # Include any provider that has rows but no budget config, so the
    # admin sees orphans too (encourages adding budgets when new providers
    # appear).
    extras_stmt = text(
        """
        SELECT DISTINCT provider
        FROM provider_usage_snapshot
        WHERE date_trunc('month', date) = date_trunc('month', NOW())
        """
    )
    extras = {r[0] for r in (await db.execute(extras_stmt)).all()}

    for provider in sorted(set(budgets) | extras):
        budget = float(budgets.get(provider, 0.0))
        accumulated = float(
            (await db.execute(sum_stmt, {"provider": provider})).scalar() or 0
        )
        ratio = (accumulated / budget) if budget > 0 else 0.0
        top_rows = (await db.execute(top_stmt, {"provider": provider})).all()
        top_models = [
            {"model": r[0], "spend_usd": float(r[1])} for r in top_rows
        ]
        result[provider] = {
            "budget_usd": budget,
            "accumulated_usd": accumulated,
            "ratio": round(ratio, 4),
            "top_models": top_models,
        }
    return result
