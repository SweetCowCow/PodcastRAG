"""Tests for `/admin/provider-usage/*` admin endpoints."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import app
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest.mark.asyncio
async def test_daily_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/provider-usage/daily")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_monthly_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/provider-usage/monthly")
        assert resp.status_code == 401


@db_required
@pytest.mark.asyncio
async def test_member_gets_403(auth_member):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/provider-usage/monthly", cookies=auth_member["cookies"]
        )
        assert resp.status_code == 403


@db_required
@pytest.mark.asyncio
async def test_daily_endpoint_returns_rows(auth_admin, db_session):
    # Seed a row
    await db_session.execute(
        text(
            "INSERT INTO provider_usage_snapshot "
            "(provider, model, date, spend_usd, raw_payload) "
            "VALUES ('aihub', 'gpt-4o-mini', :d, 1.23, '{}'::jsonb) "
            "ON CONFLICT DO NOTHING"
        ),
        {"d": date.today()},
    )
    await db_session.commit()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/provider-usage/daily",
                cookies=auth_admin["cookies"],
            )
            assert resp.status_code == 200
            body = resp.json()
            assert isinstance(body, list)
            assert any(
                row["provider"] == "aihub" and row["model"] == "gpt-4o-mini"
                for row in body
            )
    finally:
        await db_session.execute(
            text(
                "DELETE FROM provider_usage_snapshot WHERE provider='aihub' "
                "AND model='gpt-4o-mini' AND date=:d"
            ),
            {"d": date.today()},
        )
        await db_session.commit()


@db_required
@pytest.mark.asyncio
async def test_monthly_endpoint_returns_ratios(auth_admin, db_session):
    today = datetime.now(timezone.utc).date()
    # Seed: aihub $35 monthly via two rows; openai $10
    await db_session.execute(
        text("DELETE FROM provider_usage_snapshot WHERE provider IN ('aihub','openai')")
    )
    await db_session.execute(
        text(
            "INSERT INTO provider_usage_snapshot "
            "(provider, model, date, spend_usd, raw_payload) VALUES "
            "('aihub', 'gpt-4o-mini', :d, 20.0, '{}'::jsonb),"
            "('aihub', 'claude-3-haiku', :d, 15.0, '{}'::jsonb),"
            "('openai', 'whisper-1', :d, 10.0, '{}'::jsonb)"
        ),
        {"d": today},
    )
    await db_session.commit()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/provider-usage/monthly", cookies=auth_admin["cookies"]
            )
            assert resp.status_code == 200
            body = resp.json()
            assert "aihub" in body and "openai" in body
            assert body["aihub"]["accumulated_usd"] == pytest.approx(35.0)
            assert body["openai"]["accumulated_usd"] == pytest.approx(10.0)
            # ratios = spend / budget (default 80, 30)
            assert body["aihub"]["ratio"] == pytest.approx(35.0 / 80.0, rel=1e-3)
            assert body["openai"]["ratio"] == pytest.approx(10.0 / 30.0, rel=1e-3)
            # top_models present
            top_models = body["aihub"]["top_models"]
            assert len(top_models) >= 2
            top_model_names = [m["model"] for m in top_models]
            assert "gpt-4o-mini" in top_model_names
    finally:
        await db_session.execute(
            text(
                "DELETE FROM provider_usage_snapshot WHERE provider IN ('aihub','openai')"
            )
        )
        await db_session.commit()


@db_required
@pytest.mark.asyncio
async def test_daily_bad_range_400(auth_admin):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/provider-usage/daily?start=2026-05-10&end=2026-05-01",
            cookies=auth_admin["cookies"],
        )
        assert resp.status_code == 400
