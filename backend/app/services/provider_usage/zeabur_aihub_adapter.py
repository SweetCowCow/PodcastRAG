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

import asyncio
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
# Split timeout: AI Hub usage endpoint can be slow to compute aggregates
# (observed > 10s p95). Give read 30s, total budget 45s. Connect/write fast.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
DEFAULT_TOTAL_BUDGET_SECONDS = 45.0
MAX_ATTEMPTS = 3  # 1 initial + 2 retries
BACKOFF_BASE_SECONDS = 2.0  # exponential: 2s, 4s


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

    resp: httpx.Response | None = None
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = await asyncio.wait_for(
                    client.get(AIHUB_USAGE_URL, headers=headers, params=params),
                    timeout=DEFAULT_TOTAL_BUDGET_SECONDS,
                )
                break
            except (
                httpx.TimeoutException,
                httpx.TransportError,
                asyncio.TimeoutError,
            ) as exc:
                last_exc = exc
                if attempt >= MAX_ATTEMPTS:
                    # Upstream unreachable / unresponsive. Fail-open so the
                    # hourly Beat tick still records openai etc. and we don't
                    # spam alerts on a transient AI Hub outage. Loud WARNING
                    # so the gap is visible in logs / dashboards.
                    logger.warning(
                        "aihub usage unreachable after %d attempts (%r); "
                        "fail-open with empty snapshot list",
                        attempt,
                        exc,
                    )
                    return []
                backoff = BACKOFF_BASE_SECONDS ** attempt  # 2s, 4s
                logger.warning(
                    "aihub usage attempt %d/%d failed (%r); retrying in %.1fs",
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
            except httpx.HTTPError as exc:
                logger.error("aihub usage fetch failed (non-retryable): %r", exc)
                raise
    if resp is None:  # pragma: no cover — defensive
        return []

    if resp.status_code >= 500:
        # Upstream broken (502/503/504 etc). Same rationale as the timeout
        # branch above: fail-open with WARNING, don't pollute alert pipeline.
        logger.warning(
            "aihub usage upstream %s (body=%s); fail-open with empty list",
            resp.status_code,
            resp.text[:200],
        )
        return []
    if resp.status_code != 200:
        # 4xx — misconfiguration (auth, bad params). Stay loud so we notice.
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
