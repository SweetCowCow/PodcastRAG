"""OpenAI direct usage adapter.

Hits ``GET https://api.openai.com/v1/organization/costs`` which requires an
**organization admin key** (a regular project key has no ``read_usage``
scope). User produces one at:

    https://platform.openai.com/settings/organization/admin-keys

…and sets it as env ``OPENAI_ORG_ADMIN_KEY``. **Important**: this is a
distinct env from the runtime ``OPENAI_API_KEY`` so the inference key can
stay scoped to chat/embedding and not be inadvertently used for usage
reads.

Fail-open behaviour: when ``OPENAI_ORG_ADMIN_KEY`` is unset, the adapter
logs a warning and returns ``[]`` — the Beat collector continues with
other adapters rather than crashing.

Response shape (truncated):

    {"data": [
        {
            "start_time": 1714521600,
            "end_time": 1714608000,
            "results": [{"amount": {"value": 1.23}, "line_item": "gpt-4o"}]
        },
        ...
    ]}
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.provider_usage import UsageSnapshot


logger = logging.getLogger(__name__)

OPENAI_COSTS_URL = "https://api.openai.com/v1/organization/costs"
DEFAULT_TIMEOUT_SECONDS = 30.0


def _key() -> str | None:
    """Resolve org admin key at call time so tests can monkeypatch env."""
    return os.environ.get("OPENAI_ORG_ADMIN_KEY") or None


async def fetch_daily_usage(start: date, end: date) -> list["UsageSnapshot"]:
    # Local import avoids the circular dependency
    # (__init__ imports this module to build ADAPTERS).
    from app.services.provider_usage import UsageSnapshot

    token = _key()
    if not token:
        logger.warning(
            "OPENAI_ORG_ADMIN_KEY not configured, skipping"
        )
        return []

    headers = {"Authorization": f"Bearer {token}"}
    # OpenAI costs API takes unix-second timestamps for start/end.
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    params = {
        "start_time": int(start_dt.timestamp()),
        "end_time": int(end_dt.timestamp()),
        "bucket_width": "1d",
        "group_by": "line_item",
        "limit": 90,
    }

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.get(OPENAI_COSTS_URL, headers=headers, params=params)
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("openai costs fetch failed: %r", exc)
        raise

    if resp.status_code != 200:
        logger.error(
            "openai costs non-200: status=%s body=%s",
            resp.status_code,
            resp.text[:300],
        )
        resp.raise_for_status()

    payload = resp.json()
    buckets = payload.get("data") or []
    snapshots: list[UsageSnapshot] = []
    for bucket in buckets:
        start_ts = bucket.get("start_time")
        if start_ts is None:
            continue
        try:
            bucket_date = datetime.fromtimestamp(int(start_ts), tz=timezone.utc).date()
        except (ValueError, TypeError):
            logger.warning("openai costs: skipping bucket with bad start_time %r", start_ts)
            continue
        for result in bucket.get("results") or []:
            try:
                amount = result.get("amount") or {}
                value = Decimal(str(amount.get("value", "0")))
                model = result.get("line_item") or None
            except Exception:
                logger.warning(
                    "openai costs: skipping malformed result %r", result
                )
                continue
            snapshots.append(
                UsageSnapshot(
                    provider="openai",
                    model=model,
                    date=bucket_date,
                    spend_usd=value,
                    raw_payload=result,
                )
            )
    return snapshots
