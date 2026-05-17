"""Zeabur AI Hub usage adapter.

Hits the AI Hub HTTP usage endpoint directly (no dependency on the ``zeabur``
CLI binary inside the worker container — keeps the worker image slim and
avoids subprocess flakiness in PaaS environments).

Auth: ``AIHUB_USAGE_KEY`` env (Bearer token). When unset the adapter logs
a warning and returns an empty list so the Beat task can fail-open and
keep other adapters running.

Endpoint shape (as of 2026-05): ``GET https://aihub.zeabur.app/v1/usage``
returns JSON like::

    {"data": [
        {"date": "2026-05-10", "model": "gpt-4o-mini", "spend_usd": "1.23"},
        ...
    ]}

The adapter is defensive: missing/garbled fields per row are skipped (logged
at WARNING) but do not abort the whole fetch.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.provider_usage import UsageSnapshot


logger = logging.getLogger(__name__)

AIHUB_USAGE_URL = "https://aihub.zeabur.app/v1/usage"
DEFAULT_TIMEOUT_SECONDS = 30.0


def _key() -> str | None:
    """Resolve auth at call time so tests can monkeypatch env."""
    return os.environ.get("AIHUB_USAGE_KEY") or None


async def fetch_daily_usage(start: date, end: date) -> list["UsageSnapshot"]:
    # Local import avoids the circular dependency
    # (__init__ imports this module to build ADAPTERS).
    from app.services.provider_usage import UsageSnapshot

    token = _key()
    if not token:
        logger.warning(
            "AIHUB_USAGE_KEY not configured, skipping aihub usage fetch"
        )
        return []

    headers = {"Authorization": f"Bearer {token}"}
    params = {"start": start.isoformat(), "end": end.isoformat()}

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.get(AIHUB_USAGE_URL, headers=headers, params=params)
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("aihub usage fetch failed: %r", exc)
        raise

    if resp.status_code != 200:
        logger.error(
            "aihub usage non-200: status=%s body=%s",
            resp.status_code,
            resp.text[:300],
        )
        resp.raise_for_status()

    payload = resp.json()
    rows = payload.get("data") or []
    snapshots: list[UsageSnapshot] = []
    for row in rows:
        try:
            d_raw = row.get("date")
            if not d_raw:
                continue
            d = datetime.strptime(d_raw, "%Y-%m-%d").date()
            model = row.get("model") or None
            spend = Decimal(str(row.get("spend_usd", "0")))
        except (ValueError, InvalidOperation, TypeError):
            logger.warning("aihub usage: skipping malformed row %r", row)
            continue
        snapshots.append(
            UsageSnapshot(
                provider="aihub",
                model=model,
                date=d,
                spend_usd=spend,
                raw_payload=row,
            )
        )
    return snapshots
