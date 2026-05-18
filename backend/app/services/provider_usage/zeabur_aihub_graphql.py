"""Zeabur AI Hub usage adapter — GraphQL edition.

Replaces the legacy ``zeabur_aihub_adapter`` (which targeted the non-existent
``https://aihub.zeabur.app/v1/usage`` REST endpoint and silently returned
zero rows for nine days). This adapter hits Zeabur's official GraphQL
endpoint ``https://api.zeabur.com/graphql`` — the same data source used by
the ``zeabur`` CLI (`zeabur ai-hub usage`) and the ai-sdk repo.

Auth: ``ZEABUR_API_TOKEN`` env (Bearer). Token can be obtained from
``~/.config/zeabur/cli.yaml`` after running ``zeabur auth login``.

Query: ``aihubMonthlyUsage(month: String)`` returns::

    {
      "totalSpend": float,
      "dailyUsage": [
        {
          "date": "YYYY-MM-DD",
          "spend": float,
          "models": [{"model": str, "cost": float}]
        }
      ],
      "modelsCost": [...]
    }

GraphQL is monthly-grained — the adapter splits cross-month ranges into one
GraphQL POST per month, merges the responses, then filters down to entries
whose ``date`` falls within ``[start, end]``.

Failure modes (loud — no fail-open):
- ``ZEABUR_API_TOKEN`` unset → log WARNING + return ``[]`` (so the Beat
  collector can still tick other providers on first-deploy).
- 4xx → raise ``httpx.HTTPStatusError`` immediately (misconfig / bad token).
- 5xx → retry 3x with exponential backoff, then raise (Zeabur SLA is good
  enough that silent drop hides real outages; fail-loud beats fail-quiet).
- GraphQL ``errors`` field set → raise ``RuntimeError``.
- Date range spans more than 6 months → raise ``ValueError`` (defensive cap
  on accidental huge ranges that would amplify rate limits).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.provider_usage import UsageSnapshot


logger = logging.getLogger(__name__)

ZEABUR_GRAPHQL_URL = "https://api.zeabur.com/graphql"
# Split timeout: connect fast, give the monthly aggregate up to 30s to
# compute server-side, 45s total per attempt.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
DEFAULT_TOTAL_BUDGET_SECONDS = 45.0
MAX_ATTEMPTS = 3  # 1 initial + 2 retries
BACKOFF_BASE_SECONDS = 2.0  # exponential: 2s, 4s
MAX_MONTHS = 6

AIHUB_MONTHLY_USAGE_QUERY = """
query AihubMonthlyUsage($month: String!) {
  aihubMonthlyUsage(month: $month) {
    totalSpend
    dailyUsage {
      date
      spend
      models {
        model
        cost
      }
    }
    modelsCost {
      model
      cost
    }
  }
}
""".strip()


def _token() -> str | None:
    """Resolve auth at call time so tests can monkeypatch env."""
    return os.environ.get("ZEABUR_API_TOKEN") or None


def _iter_months(start: date, end: date) -> list[str]:
    """Return ``YYYY-MM`` strings covering every month touched by [start, end]."""
    if end < start:
        return []
    months: list[str] = []
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cursor <= last:
        months.append(f"{cursor.year:04d}-{cursor.month:02d}")
        # Advance one month (cursor is always day=1).
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


async def _post_one_month(
    client: httpx.AsyncClient, token: str, month: str
) -> dict:
    """POST a single month's GraphQL query with retry/backoff. Returns ``data.aihubMonthlyUsage``."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "query": AIHUB_MONTHLY_USAGE_QUERY,
        "variables": {"month": month},
    }

    last_5xx_exc: httpx.HTTPStatusError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = await asyncio.wait_for(
            client.post(ZEABUR_GRAPHQL_URL, headers=headers, json=body),
            timeout=DEFAULT_TOTAL_BUDGET_SECONDS,
        )
        if 400 <= resp.status_code < 500:
            # 4xx — misconfig / auth. Fail loudly, no retry.
            logger.error(
                "aihub graphql 4xx: status=%s month=%s body=%s",
                resp.status_code,
                month,
                resp.text[:300],
            )
            resp.raise_for_status()
        if resp.status_code >= 500:
            # Build a real HTTPStatusError to raise after retries.
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_5xx_exc = exc
            if attempt >= MAX_ATTEMPTS:
                logger.error(
                    "aihub graphql 5xx after %d attempts month=%s status=%s",
                    attempt,
                    month,
                    resp.status_code,
                )
                assert last_5xx_exc is not None  # for type-checker
                raise last_5xx_exc
            backoff = BACKOFF_BASE_SECONDS ** attempt  # 2s, 4s
            logger.warning(
                "aihub graphql 5xx attempt %d/%d month=%s status=%s; retrying in %.1fs",
                attempt,
                MAX_ATTEMPTS,
                month,
                resp.status_code,
                backoff,
            )
            await asyncio.sleep(backoff)
            continue

        # 2xx path
        payload = resp.json()
        errors = payload.get("errors")
        if errors:
            raise RuntimeError(f"GraphQL errors: {errors}")
        data = payload.get("data") or {}
        return data.get("aihubMonthlyUsage") or {}

    # Defensive — loop should have either returned or raised.
    if last_5xx_exc is not None:  # pragma: no cover
        raise last_5xx_exc
    return {}  # pragma: no cover


async def fetch_daily_usage(start: date, end: date) -> list["UsageSnapshot"]:
    """Fetch AI Hub daily spend via Zeabur GraphQL ``aihubMonthlyUsage``.

    Splits cross-month ranges into one GraphQL request per month, merges the
    responses, then filters down to ``start <= snapshot.date <= end``. Each
    ``(date, model)`` pair from the GraphQL ``models`` breakdown produces one
    ``UsageSnapshot``. ``ZEABUR_API_TOKEN`` env is required; when unset the
    adapter logs a warning and returns ``[]`` (fail-open on first deploy).
    """
    # Local import avoids circular dependency.
    from app.services.provider_usage import UsageSnapshot

    token = _token()
    if not token:
        logger.warning(
            "ZEABUR_API_TOKEN not configured, skipping aihub usage fetch"
        )
        return []

    months = _iter_months(start, end)
    if len(months) > MAX_MONTHS:
        raise ValueError(
            f"Date range too large: max {MAX_MONTHS} months, got {len(months)}"
        )

    snapshots: list[UsageSnapshot] = []
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        for month in months:
            monthly = await _post_one_month(client, token, month)
            daily_rows = monthly.get("dailyUsage") or []
            for day in daily_rows:
                d_raw = day.get("date")
                if not d_raw:
                    continue
                try:
                    d = datetime.strptime(d_raw, "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    logger.warning(
                        "aihub graphql: skipping bad date %r in month %s",
                        d_raw,
                        month,
                    )
                    continue
                if d < start or d > end:
                    continue
                models = day.get("models") or []
                for m_entry in models:
                    model = m_entry.get("model") or None
                    try:
                        spend = Decimal(str(m_entry.get("cost", "0")))
                    except (InvalidOperation, TypeError):
                        logger.warning(
                            "aihub graphql: skipping bad cost %r date=%s",
                            m_entry,
                            d_raw,
                        )
                        continue
                    snapshots.append(
                        UsageSnapshot(
                            provider="aihub",
                            model=model,
                            date=d,
                            spend_usd=spend,
                            raw_payload={
                                "date": d_raw,
                                "model": model,
                                "spend": float(spend),
                            },
                        )
                    )
    return snapshots


# Exported for tests that need to assert against the constants.
__all__ = [
    "fetch_daily_usage",
    "ZEABUR_GRAPHQL_URL",
    "AIHUB_MONTHLY_USAGE_QUERY",
    "MAX_MONTHS",
]


# Helper used in tests to enumerate months without hitting the network.
def _months_for_range(start: date, end: date) -> list[str]:  # pragma: no cover
    return _iter_months(start, end)
