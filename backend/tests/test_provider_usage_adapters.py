"""Unit tests for provider usage adapters (non-AI-Hub).

The AI Hub adapter tests live in ``tests/services/test_aihub_graphql_adapter.py``
since the migration to Zeabur's GraphQL endpoint
(aihub-graphql-adapter-migration change). This file now only covers the
OpenAI direct adapter.

Mocks httpx so no live HTTP traffic and no secret env required.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest

from app.services.provider_usage import UsageSnapshot, openai_adapter


class _FakeResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = "ok"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=None, response=None  # type: ignore[arg-type]
            )


class _FakeClient:
    def __init__(self, resp: _FakeResp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        return self._resp


def _patch_client(monkeypatch, module, resp: _FakeResp):
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda *a, **kw: _FakeClient(resp))


# ── OpenAI ────────────────────────────────────────────────────────────


def _ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


@pytest.mark.asyncio
async def test_openai_adapter_parses_buckets(monkeypatch):
    monkeypatch.setenv("OPENAI_ORG_ADMIN_KEY", "sk-admin-test")
    d1 = date(2026, 5, 9)
    d2 = date(2026, 5, 10)
    payload = {
        "data": [
            {
                "start_time": _ts(d1),
                "end_time": _ts(d1) + 86400,
                "results": [
                    {"amount": {"value": 0.5}, "line_item": "text-embedding-3-small"},
                    {"amount": {"value": 2.1}, "line_item": "whisper-1"},
                ],
            },
            {
                "start_time": _ts(d2),
                "end_time": _ts(d2) + 86400,
                "results": [
                    {"amount": {"value": 0.7}, "line_item": "text-embedding-3-small"},
                ],
            },
        ]
    }
    _patch_client(monkeypatch, openai_adapter, _FakeResp(200, payload))
    snaps = await openai_adapter.fetch_daily_usage(d1, d2)
    assert len(snaps) == 3
    assert all(s.provider == "openai" for s in snaps)
    by_model = {(s.date, s.model): s.spend_usd for s in snaps}
    assert by_model[(d1, "text-embedding-3-small")] == Decimal("0.5")
    assert by_model[(d1, "whisper-1")] == Decimal("2.1")
    assert by_model[(d2, "text-embedding-3-small")] == Decimal("0.7")


@pytest.mark.asyncio
async def test_openai_adapter_without_admin_key_returns_empty(monkeypatch, caplog):
    monkeypatch.delenv("OPENAI_ORG_ADMIN_KEY", raising=False)
    snaps = await openai_adapter.fetch_daily_usage(date(2026, 5, 1), date(2026, 5, 10))
    assert snaps == []
    # The warning is the "fail-open" contract documented in the spec.
    assert any("OPENAI_ORG_ADMIN_KEY" in r.message for r in caplog.records)
