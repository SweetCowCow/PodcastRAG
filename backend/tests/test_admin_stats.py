"""Tests for /admin/stats endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest.mark.asyncio
async def test_admin_stats_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/stats")
        assert resp.status_code == 401
        assert resp.json()["detail"]["error_code"] == "not_authenticated"


@db_required
@pytest.mark.asyncio
async def test_admin_stats_member_returns_403(auth_member):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/stats", cookies=auth_member["cookies"])
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "forbidden"


@db_required
@pytest.mark.asyncio
async def test_admin_stats_admin_returns_counts(auth_admin):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/stats", cookies=auth_admin["cookies"])
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "episodes_completed",
            "transcript_chunks",
            "shows",
            "users",
        }
        for k in body:
            assert isinstance(body[k], int)
            assert body[k] >= 0
        # at least 1 user exists (the admin we just created)
        assert body["users"] >= 1
