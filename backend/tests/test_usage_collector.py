"""Tests for the hourly usage_collector beat task.

DB-touching tests are guarded by ``_postgres_reachable``. Pure-unit logic
(per-adapter isolation, return shape) is mocked end-to-end against a fake
ADAPTERS dict.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.provider_usage import UsageSnapshot
from app.workers import usage_collector
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest.mark.asyncio
async def test_collector_calls_every_adapter_and_isolates_failures(monkeypatch):
    calls: list[str] = []

    async def good(start, end):
        calls.append("good")
        return [
            UsageSnapshot(
                provider="good",
                model="m1",
                date=date(2026, 5, 10),
                spend_usd=Decimal("1.0"),
                raw_payload={},
            )
        ]

    async def bad(start, end):
        calls.append("bad")
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(
        usage_collector, "ADAPTERS", {"good": good, "bad": bad}, raising=True
    )

    # Stub the upsert helper so we don't need a live DB for this isolation test.
    async def _stub_upsert(db, snapshots):
        return None

    monkeypatch.setattr(usage_collector, "_upsert_snapshots", _stub_upsert)

    # Stub the engine / session — return a no-op session so the loop runs.
    class _NoopSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def commit(self):
            return None

    class _NoopMaker:
        def __call__(self):
            return _NoopSession()

    class _NoopEngine:
        async def dispose(self):
            return None

    monkeypatch.setattr(
        usage_collector,
        "create_async_engine",
        lambda *a, **kw: _NoopEngine(),
    )
    monkeypatch.setattr(
        usage_collector,
        "async_sessionmaker",
        lambda engine, expire_on_commit=False: _NoopMaker(),
    )

    result = await usage_collector._run()
    # both adapters tried
    assert set(calls) == {"good", "bad"}
    # good succeeded
    assert result["counts"]["good"] == 1
    # bad isolated as an error, did not crash run
    assert "bad" in result["errors"]
    assert "simulated upstream failure" in result["errors"]["bad"]


@db_required
@pytest.mark.asyncio
async def test_collector_upserts_into_real_db(monkeypatch, db_session):
    """End-to-end with a real Postgres: write + re-write same key updates."""
    from sqlalchemy import text

    async def fake_fetch(start, end):
        return [
            UsageSnapshot(
                provider="testprov",
                model="modelA",
                date=date(2026, 5, 10),
                spend_usd=Decimal("1.50"),
                raw_payload={"a": 1},
            )
        ]

    monkeypatch.setattr(
        usage_collector, "ADAPTERS", {"testprov": fake_fetch}, raising=True
    )

    # Clean up any prior test rows.
    await db_session.execute(
        text("DELETE FROM provider_usage_snapshot WHERE provider='testprov'")
    )
    await db_session.commit()

    result = await usage_collector._run()
    assert result["counts"]["testprov"] == 1

    # Verify row written.
    row = (
        await db_session.execute(
            text(
                "SELECT spend_usd FROM provider_usage_snapshot "
                "WHERE provider='testprov' AND model='modelA' AND date=:d"
            ),
            {"d": date(2026, 5, 10)},
        )
    ).first()
    assert row is not None
    assert Decimal(str(row[0])) == Decimal("1.50")

    # Re-run with a different spend → upsert overwrites.
    async def fake_fetch2(start, end):
        return [
            UsageSnapshot(
                provider="testprov",
                model="modelA",
                date=date(2026, 5, 10),
                spend_usd=Decimal("2.75"),
                raw_payload={"a": 2},
            )
        ]

    monkeypatch.setattr(
        usage_collector, "ADAPTERS", {"testprov": fake_fetch2}, raising=True
    )
    await usage_collector._run()
    rows = (
        await db_session.execute(
            text(
                "SELECT COUNT(*), MAX(spend_usd) FROM provider_usage_snapshot "
                "WHERE provider='testprov' AND model='modelA' AND date=:d"
            ),
            {"d": date(2026, 5, 10)},
        )
    ).first()
    assert rows[0] == 1
    assert Decimal(str(rows[1])) == Decimal("2.75")

    # Cleanup
    await db_session.execute(
        text("DELETE FROM provider_usage_snapshot WHERE provider='testprov'")
    )
    await db_session.commit()
