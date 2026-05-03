"""E2E login backdoor — endpoint, rate limiter, route gating, TTL."""

import importlib
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from .conftest import _postgres_reachable

VALID_TOKEN = "x" * 64
ADMIN_EMAIL = "pytest-e2e-admin@example.com"


# ─── App rebuild helpers ─────────────────────────────────────────────────


def _rebuild_app(monkeypatch, *, e2e_token: str | None):
    """Mutate settings + rebuild app with a specific E2E_LOGIN_TOKEN."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "e2e_login_token", e2e_token or None)
    monkeypatch.setattr(settings, "admin_emails", ADMIN_EMAIL)

    # Build a fresh FastAPI app that mirrors main.py's wiring but reads the
    # current settings.e2e_login_token rather than the import-time snapshot.
    from fastapi import FastAPI

    from app.api.admin import router as admin_router
    from app.api.auth import me_router, router as auth_router
    from app.api.auth_e2e import router as auth_e2e_router
    from app.api.episodes import router as episodes_router
    from app.api.health import router as health_router
    from app.api.query import router as query_router
    from app.api.queue import router as queue_router
    from app.api.schedules import router as schedules_router
    from app.api.settings import router as settings_router
    from app.api.shows import router as shows_router, rss_preview_router
    from app.api.stats import router as stats_router
    from app.api.transcripts import router as transcripts_router
    from app.api.users import router as users_router

    app = FastAPI()
    for r in (
        health_router, auth_router, me_router, shows_router, rss_preview_router,
        schedules_router, episodes_router, transcripts_router, query_router,
        admin_router, queue_router, settings_router, users_router, stats_router,
    ):
        app.include_router(r)
    if settings.e2e_login_token:
        app.include_router(auth_e2e_router)
    return app


# ─── DB seeding ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def admin_user(db_session):
    """Seed an active admin user with email matching ADMIN_EMAIL."""
    from app.models.user import User, UserRole, UserStatus

    await db_session.execute(delete(User).where(User.email == ADMIN_EMAIL))
    await db_session.commit()

    user = User(
        email=ADMIN_EMAIL,
        name="pytest e2e admin",
        provider="google",
        google_sub=f"google-sub-e2e-{secrets.token_hex(4)}",
        role=UserRole.admin.value,
        status=UserStatus.active.value,
        quota_remaining=100,
        quota_initial=100,
        total_queries=0,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.execute(delete(User).where(User.email == ADMIN_EMAIL))
    await db_session.commit()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.api.auth_e2e import _reset_rate_limit

    _reset_rate_limit()
    yield
    _reset_rate_limit()


# ─── Section 5: route gating ─────────────────────────────────────────────


def test_disabled_deployment_returns_404(monkeypatch):
    app = _rebuild_app(monkeypatch, e2e_token=None)
    client = TestClient(app)
    r = client.get("/auth/_e2e_login?token=anything")
    assert r.status_code == 404


def test_empty_token_env_returns_404(monkeypatch):
    app = _rebuild_app(monkeypatch, e2e_token="")
    client = TestClient(app)
    r = client.get("/auth/_e2e_login?token=anything")
    assert r.status_code == 404


def test_route_registered_when_token_set_returns_401_on_wrong_token(monkeypatch):
    app = _rebuild_app(monkeypatch, e2e_token=VALID_TOKEN)
    client = TestClient(app)
    r = client.get("/auth/_e2e_login?token=wrong")
    assert r.status_code == 401


# ─── Section 2: TTL override unit test ───────────────────────────────────


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_create_session_default_ttl(db_session, admin_user):
    from app.core.config import settings
    from app.services.session_service import create_session

    issued = await create_session(db_session, user_id=admin_user.id)
    delta = issued.expires_at - datetime.now(timezone.utc)
    expected = timedelta(days=settings.session_ttl_days)
    assert abs(delta.total_seconds() - expected.total_seconds()) < 60


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_create_session_ttl_override(db_session, admin_user):
    from app.services.session_service import create_session

    issued = await create_session(
        db_session, user_id=admin_user.id, ttl_override=timedelta(minutes=15)
    )
    delta = issued.expires_at - datetime.now(timezone.utc)
    assert abs(delta.total_seconds() - 15 * 60) < 5


# ─── Section 3: rate limiter unit tests ──────────────────────────────────


def test_rate_limit_blocks_after_5_failures(monkeypatch):
    from app.api import auth_e2e

    auth_e2e._reset_rate_limit()
    ip = "1.2.3.4"
    for _ in range(5):
        assert auth_e2e._check_rate_limit(ip) is True
        auth_e2e._record_failure(ip)
    # 6th check: 5 failures recorded, list length 5, > 5 is False so still allowed.
    # Record 6th failure to reach > 5.
    assert auth_e2e._check_rate_limit(ip) is True
    auth_e2e._record_failure(ip)
    # Now 6 failures — > 5 → blocked.
    assert auth_e2e._check_rate_limit(ip) is False


def test_rate_limit_resets_after_window(monkeypatch):
    from app.api import auth_e2e

    auth_e2e._reset_rate_limit()
    ip = "5.6.7.8"
    base = 1000.0
    times = iter([base + i * 0.1 for i in range(10)])
    monkeypatch.setattr(auth_e2e.time, "monotonic", lambda: next(times))
    for _ in range(6):
        auth_e2e._record_failure(ip)

    # Jump past the window
    monkeypatch.setattr(
        auth_e2e.time, "monotonic", lambda: base + auth_e2e.RATE_LIMIT_WINDOW_SECONDS + 1
    )
    assert auth_e2e._check_rate_limit(ip) is True
    assert _failure_log_size(ip) == 0


def _failure_log_size(ip: str) -> int:
    from app.api.auth_e2e import _failure_log

    return len(_failure_log.get(ip, []))


# ─── Section 6: full endpoint integration tests ──────────────────────────


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_valid_token_issues_session(monkeypatch, db_session, admin_user):
    app = _rebuild_app(monkeypatch, e2e_token=VALID_TOKEN)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/auth/_e2e_login?token={VALID_TOKEN}")
    assert r.status_code == 302
    assert "session_id" in r.cookies
    assert "csrf_token" in r.cookies

    from app.core.security import hash_token
    from app.models.session import Session as SessionRow

    token_hash = hash_token(r.cookies["session_id"])
    result = await db_session.execute(
        select(SessionRow).where(SessionRow.session_token_hash == token_hash)
    )
    row = result.scalar_one()
    assert row.user_id == admin_user.id
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delta = expires_at - datetime.now(timezone.utc)
    assert abs(delta.total_seconds() - 15 * 60) < 30


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_invalid_token_returns_401(monkeypatch, db_session, admin_user, caplog):
    app = _rebuild_app(monkeypatch, e2e_token=VALID_TOKEN)
    import logging
    with caplog.at_level(logging.WARNING):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/auth/_e2e_login?token=wrong-token-of-sufficient-length-yes")
    assert r.status_code == 401
    assert "session_id" not in r.cookies
    assert any(
        getattr(rec, "event", None) == "e2e_login_attempt" and getattr(rec, "success", None) is False
        for rec in caplog.records
    )


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_missing_token_returns_401(monkeypatch, db_session, admin_user):
    app = _rebuild_app(monkeypatch, e2e_token=VALID_TOKEN)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/auth/_e2e_login")
    assert r.status_code == 401


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_rate_limit_blocks_6th_failure_without_compare(monkeypatch, db_session, admin_user):
    app = _rebuild_app(monkeypatch, e2e_token=VALID_TOKEN)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(6):
            await c.get("/auth/_e2e_login?token=wrong")

        with patch("app.api.auth_e2e.hmac.compare_digest") as mock_cmp:
            r = await c.get("/auth/_e2e_login?token=wrong")
            assert r.status_code == 429
            mock_cmp.assert_not_called()


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_successful_calls_do_not_consume_rate_limit(monkeypatch, db_session, admin_user):
    app = _rebuild_app(monkeypatch, e2e_token=VALID_TOKEN)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(10):
            r = await c.get(f"/auth/_e2e_login?token={VALID_TOKEN}")
            assert r.status_code == 302
    # No failures recorded for any IP.
    from app.api.auth_e2e import _failure_log
    assert all(len(v) == 0 for v in _failure_log.values())
