"""Unit tests for the Zeabur AI Hub GraphQL usage adapter.

Mocks ``httpx.AsyncClient`` so no live HTTP traffic, no real token needed.
Covers the seven scenarios from the change spec (aihub-graphql-adapter-migration):

1. Single-month range returns one snapshot per (date, model)
2. Cross-month range issues exactly one POST per month
3. Missing ZEABUR_API_TOKEN → [] + log warning (no exception)
4. 5xx → retry 3 times then raise HTTPStatusError (no fail-open)
5. 4xx → raise immediately, no retry
6. GraphQL ``errors`` field → raise RuntimeError
7. Date range > 6 months → raise ValueError
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.services.provider_usage import UsageSnapshot, zeabur_aihub_graphql


# ── Fakes ─────────────────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or "ok"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("POST", zeabur_aihub_graphql.ZEABUR_GRAPHQL_URL),
                response=httpx.Response(self.status_code),
            )


class _FakeClient:
    """Records every POST call and returns scripted responses in order.

    If ``responses`` is shorter than the number of calls, the last response is
    repeated (useful for "always 503" retry tests). If a single ``_FakeResp``
    is passed, it's used for every call.
    """

    def __init__(self, responses):
        if isinstance(responses, _FakeResp):
            responses = [responses]
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if len(self.calls) <= len(self._responses):
            return self._responses[len(self.calls) - 1]
        return self._responses[-1]


def _install_client(monkeypatch, fake: _FakeClient):
    monkeypatch.setattr(
        zeabur_aihub_graphql.httpx,
        "AsyncClient",
        lambda *a, **kw: fake,
    )


async def _noop_sleep(*_a, **_kw):
    return None


# ── 1. Single month ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_month_returns_snapshots(monkeypatch):
    monkeypatch.setenv("ZEABUR_API_TOKEN", "test-token")
    payload = {
        "data": {
            "aihubMonthlyUsage": {
                "totalSpend": 3.78,
                "dailyUsage": [
                    {
                        "date": "2026-05-09",
                        "spend": 1.78,
                        "models": [
                            {"model": "gpt-4o-mini", "cost": 1.23},
                            {"model": "claude-3-haiku", "cost": 0.55},
                        ],
                    },
                    {
                        "date": "2026-05-10",
                        "spend": 2.00,
                        "models": [
                            {"model": "gpt-4o-mini", "cost": 1.50},
                            {"model": "claude-3-haiku", "cost": 0.50},
                        ],
                    },
                ],
                "modelsCost": [],
            }
        }
    }
    fake = _FakeClient(_FakeResp(200, payload))
    _install_client(monkeypatch, fake)

    snaps = await zeabur_aihub_graphql.fetch_daily_usage(
        date(2026, 5, 9), date(2026, 5, 10)
    )

    assert len(snaps) == 4
    assert all(isinstance(s, UsageSnapshot) for s in snaps)
    assert {s.provider for s in snaps} == {"aihub"}
    by_key = {(s.date, s.model): s.spend_usd for s in snaps}
    assert by_key[(date(2026, 5, 9), "gpt-4o-mini")] == Decimal("1.23")
    assert by_key[(date(2026, 5, 9), "claude-3-haiku")] == Decimal("0.55")
    assert by_key[(date(2026, 5, 10), "gpt-4o-mini")] == Decimal("1.50")
    # Exactly one HTTP POST for a single-month range.
    assert len(fake.calls) == 1
    assert fake.calls[0]["json"]["variables"] == {"month": "2026-05"}


# ── 2. Cross-month range ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_month_range_splits_queries(monkeypatch):
    monkeypatch.setenv("ZEABUR_API_TOKEN", "test-token")

    def _month_payload(month: str, daily: list[dict]) -> dict:
        return {
            "data": {
                "aihubMonthlyUsage": {
                    "totalSpend": 0.0,
                    "dailyUsage": daily,
                    "modelsCost": [],
                }
            }
        }

    april_payload = _month_payload(
        "2026-04",
        [
            # In-range
            {
                "date": "2026-04-29",
                "spend": 1.0,
                "models": [{"model": "m1", "cost": 1.0}],
            },
            {
                "date": "2026-04-30",
                "spend": 2.0,
                "models": [{"model": "m1", "cost": 2.0}],
            },
            # Out-of-range — should be filtered out.
            {
                "date": "2026-04-15",
                "spend": 5.0,
                "models": [{"model": "m1", "cost": 5.0}],
            },
        ],
    )
    may_payload = _month_payload(
        "2026-05",
        [
            {
                "date": "2026-05-01",
                "spend": 3.0,
                "models": [{"model": "m1", "cost": 3.0}],
            },
            {
                "date": "2026-05-02",
                "spend": 4.0,
                "models": [{"model": "m1", "cost": 4.0}],
            },
            # Out-of-range
            {
                "date": "2026-05-15",
                "spend": 9.0,
                "models": [{"model": "m1", "cost": 9.0}],
            },
        ],
    )

    fake = _FakeClient(
        [_FakeResp(200, april_payload), _FakeResp(200, may_payload)]
    )
    _install_client(monkeypatch, fake)

    snaps = await zeabur_aihub_graphql.fetch_daily_usage(
        date(2026, 4, 29), date(2026, 5, 2)
    )

    # 2 POSTs, one per month.
    assert len(fake.calls) == 2
    months_requested = [c["json"]["variables"]["month"] for c in fake.calls]
    assert months_requested == ["2026-04", "2026-05"]

    # 4 in-range snapshots: 4-29, 4-30, 5-1, 5-2.
    dates = sorted(s.date for s in snaps)
    assert dates == [
        date(2026, 4, 29),
        date(2026, 4, 30),
        date(2026, 5, 1),
        date(2026, 5, 2),
    ]
    assert all(date(2026, 4, 29) <= s.date <= date(2026, 5, 2) for s in snaps)


# ── 3. Missing token ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_token_returns_empty_with_warning(monkeypatch, caplog):
    monkeypatch.delenv("ZEABUR_API_TOKEN", raising=False)

    with caplog.at_level("WARNING"):
        snaps = await zeabur_aihub_graphql.fetch_daily_usage(
            date(2026, 5, 1), date(2026, 5, 10)
        )

    assert snaps == []
    assert any(
        "ZEABUR_API_TOKEN not configured" in r.message for r in caplog.records
    )


# ── 4. 5xx exhausts retries then raises ──────────────────────────────


@pytest.mark.asyncio
async def test_5xx_raises_after_retries(monkeypatch):
    monkeypatch.setenv("ZEABUR_API_TOKEN", "test-token")
    fake = _FakeClient(
        [_FakeResp(503), _FakeResp(503), _FakeResp(503)]
    )
    _install_client(monkeypatch, fake)
    monkeypatch.setattr(zeabur_aihub_graphql.asyncio, "sleep", _noop_sleep)

    with pytest.raises(httpx.HTTPStatusError):
        await zeabur_aihub_graphql.fetch_daily_usage(
            date(2026, 5, 1), date(2026, 5, 2)
        )

    # Confirm all 3 attempts were made (no fail-open early return).
    assert len(fake.calls) == zeabur_aihub_graphql.MAX_ATTEMPTS == 3


# ── 5. 4xx raises immediately (no retry) ─────────────────────────────


@pytest.mark.asyncio
async def test_4xx_raises_immediately(monkeypatch):
    monkeypatch.setenv("ZEABUR_API_TOKEN", "bad-token")
    fake = _FakeClient(_FakeResp(401))
    _install_client(monkeypatch, fake)
    monkeypatch.setattr(zeabur_aihub_graphql.asyncio, "sleep", _noop_sleep)

    with pytest.raises(httpx.HTTPStatusError):
        await zeabur_aihub_graphql.fetch_daily_usage(
            date(2026, 5, 1), date(2026, 5, 2)
        )

    # No retry for 4xx — exactly one call.
    assert len(fake.calls) == 1


# ── 6. GraphQL errors field ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_graphql_errors_field_raises(monkeypatch):
    monkeypatch.setenv("ZEABUR_API_TOKEN", "test-token")
    payload = {
        "data": None,
        "errors": [{"message": "unauthorized: token expired"}],
    }
    fake = _FakeClient(_FakeResp(200, payload))
    _install_client(monkeypatch, fake)

    with pytest.raises(RuntimeError, match="GraphQL errors"):
        await zeabur_aihub_graphql.fetch_daily_usage(
            date(2026, 5, 1), date(2026, 5, 2)
        )


# ── 7. Oversize range → ValueError ───────────────────────────────────


@pytest.mark.asyncio
async def test_range_over_6_months_raises_value_error(monkeypatch):
    monkeypatch.setenv("ZEABUR_API_TOKEN", "test-token")

    with pytest.raises(ValueError, match="Date range too large"):
        await zeabur_aihub_graphql.fetch_daily_usage(
            date(2025, 1, 1), date(2026, 5, 1)
        )
