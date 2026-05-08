"""Tests for /admin/topic-seg/audit-sample endpoint."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest.mark.asyncio
async def test_audit_sample_unauthenticated_401():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/admin/topic-seg/audit-sample")
        assert r.status_code == 401


@db_required
@pytest.mark.asyncio
async def test_audit_sample_member_403(auth_member):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/admin/topic-seg/audit-sample", cookies=auth_member["cookies"]
        )
        assert r.status_code == 403


@db_required
@pytest.mark.asyncio
async def test_audit_sample_default_n(auth_admin):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/admin/topic-seg/audit-sample", cookies=auth_admin["cookies"]
        )
        assert r.status_code == 200
        body = r.json()
        # at most 50 by default; may be empty in test DB
        assert len(body) <= 50


@db_required
@pytest.mark.asyncio
async def test_audit_sample_n_clamped(auth_admin):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        # n=300 (above max 200) should be rejected at validation
        r = await c.get(
            "/admin/topic-seg/audit-sample?n=300",
            cookies=auth_admin["cookies"],
        )
        assert r.status_code == 422
