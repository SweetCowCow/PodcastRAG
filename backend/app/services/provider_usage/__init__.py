"""Multi-provider usage monitoring — adapter registry.

Each provider adapter exposes the same callable signature::

    async def fetch_daily_usage(start: date, end: date) -> list[UsageSnapshot]

so the hourly Beat collector can iterate ``ADAPTERS`` generically. Adding a
new provider (e.g. ``deepgram``, ``anthropic-direct``) only requires:

1. Writing ``<provider>_adapter.py`` with a ``fetch_daily_usage`` async fn
2. Registering the module's callable in ``ADAPTERS`` here

No schema migration is required because the snapshot table is generic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Awaitable, Callable

from app.services.provider_usage.openai_adapter import (
    fetch_daily_usage as openai_fetch,
)
from app.services.provider_usage.zeabur_aihub_adapter import (
    fetch_daily_usage as aihub_fetch,
)


@dataclass(frozen=True)
class UsageSnapshot:
    """One observation of provider spend on a single calendar date.

    ``model`` may be ``None`` if the provider only exposes aggregate daily
    spend; the upsert constraint treats NULL-model as the aggregate row for
    that ``(provider, date)``.
    """

    provider: str
    model: str | None
    date: date
    spend_usd: Decimal
    raw_payload: dict = field(default_factory=dict)


AdapterFn = Callable[[date, date], Awaitable[list[UsageSnapshot]]]

# Provider id → async fetch function. Key strings must match the values
# written to ``provider_usage_snapshot.provider``.
ADAPTERS: dict[str, AdapterFn] = {
    "aihub": aihub_fetch,
    "openai": openai_fetch,
}


__all__ = ["UsageSnapshot", "ADAPTERS", "AdapterFn"]
