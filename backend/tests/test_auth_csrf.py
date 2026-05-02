"""CSRF + Origin middleware tests (Task 11.3).

These tests exercise the middleware in isolation — no DB required because
unauthenticated state-changing requests are blocked before any DB lookup.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_get_request_bypasses_csrf():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET / has no auth requirement and bypasses CSRF entirely
        resp = await client.get("/")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_post_without_origin_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/admin/users")
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"]["error_code"] == "origin_missing"


@pytest.mark.asyncio
async def test_post_with_foreign_origin_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/admin/users",
            headers={"Origin": "https://evil.example.com"},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"]["error_code"] == "origin_forbidden"


@pytest.mark.asyncio
async def test_post_missing_csrf_header_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Origin OK, no CSRF header
        resp = await client.post(
            "/admin/users",
            headers={"Origin": "http://localhost:8080"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "csrf_token_missing"


@pytest.mark.asyncio
async def test_post_csrf_header_mismatch_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/admin/users",
            headers={
                "Origin": "http://localhost:8080",
                "X-CSRF-Token": "bogus",
            },
            cookies={"csrf_token": "different-value"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "csrf_token_invalid"


@pytest.mark.asyncio
async def test_post_csrf_match_passes_to_auth_check():
    """When CSRF matches, the request reaches require_admin which then
    rejects unauthenticated → 401 not_authenticated (proves CSRF passed)."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/admin/users/{fake_id}",
            headers={
                "Origin": "http://localhost:8080",
                "X-CSRF-Token": "matching-token",
            },
            cookies={"csrf_token": "matching-token"},
            json={"role": "member"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["error_code"] == "not_authenticated"


@pytest.mark.asyncio
async def test_oauth_callback_path_is_exempt_from_csrf():
    """Callback runs BEFORE the user has a session, so it must bypass CSRF.
    But it's GET anyway, so this just sanity-checks the middleware list."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET to callback without code → 400 (not 403 from CSRF)
        resp = await client.get("/auth/google/callback")
        assert resp.status_code == 400
        assert resp.json()["detail"]["error_code"] == "invalid_oauth_state"
