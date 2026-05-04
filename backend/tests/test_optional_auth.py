"""Tests for app.core.security.optional_auth_with_ip_limit dependency.

Hits the dependency through a small in-test FastAPI app that mounts an
endpoint with the dependency, then drives requests via httpx.AsyncClient.
"""
import socket
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory, get_db
from app.core.rate_limit import KEY_PREFIX, _get_redis
from app.core.security import optional_auth_with_ip_limit
from app.models.user import User

from .conftest import _postgres_reachable, _seed_user, _seed_session, csrf_headers


def _redis_reachable() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", 6379))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _build_app():
    app = FastAPI()

    @app.get("/probe")
    async def probe(user: User | None = Depends(optional_auth_with_ip_limit)):
        return {"email": user.email if user else None}

    return app


@pytest_asyncio.fixture
async def app_with_db():
    app = _build_app()

    async def _override_get_db():
        async with AsyncSessionFactory() as db:
            yield db

    app.dependency_overrides[get_db] = _override_get_db
    yield app


@pytest_asyncio.fixture
async def fresh_ip():
    """Yield a unique IP and clean up its Redis key after."""
    ip = f"10.99.{uuid.uuid4().int % 256}.{uuid.uuid4().int % 256}"
    yield ip
    r = _get_redis()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    r.delete(f"{KEY_PREFIX}:{ip}:{today}")


@pytest.mark.skipif(
    not (_postgres_reachable() and _redis_reachable()),
    reason="postgres or redis not reachable",
)
@pytest.mark.asyncio
async def test_authenticated_returns_user_no_counter(app_with_db, fresh_ip):
    async with AsyncSessionFactory() as db:
        user = await _seed_user(db, role="member")
        token = await _seed_session(db, user.id)

    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/probe",
            cookies={"session_id": token},
            headers={"x-forwarded-for": fresh_ip},
        )
    assert resp.status_code == 200
    assert resp.json()["email"] == user.email

    # IP counter MUST NOT be touched
    r = _get_redis()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert r.get(f"{KEY_PREFIX}:{fresh_ip}:{today}") is None

    async with AsyncSessionFactory() as db:
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()


@pytest.mark.skipif(not _redis_reachable(), reason="redis not reachable")
@pytest.mark.asyncio
async def test_anonymous_under_limit_returns_none(app_with_db, fresh_ip):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/probe", headers={"x-forwarded-for": fresh_ip})
    assert resp.status_code == 200
    assert resp.json() == {"email": None}

    r = _get_redis()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert int(r.get(f"{KEY_PREFIX}:{fresh_ip}:{today}")) == 1


@pytest.mark.skipif(not _redis_reachable(), reason="redis not reachable")
@pytest.mark.asyncio
async def test_anonymous_over_limit_raises_429(app_with_db, fresh_ip, monkeypatch):
    # Force limit=2 for fast test
    from app.core import config as cfg

    monkeypatch.setattr(
        cfg.settings, "ip_search_rate_limit_per_day", 2, raising=False
    )

    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for _ in range(2):
            resp = await ac.get("/probe", headers={"x-forwarded-for": fresh_ip})
            assert resp.status_code == 200
        # 3rd call exceeds
        resp = await ac.get("/probe", headers={"x-forwarded-for": fresh_ip})
    assert resp.status_code == 429
    body = resp.json()
    assert body["detail"]["error_code"] == "ip_rate_limited"
    assert body["detail"]["limit"] == 2
    assert "reset_at_utc" in body["detail"]


@pytest.mark.skipif(
    not (_postgres_reachable() and _redis_reachable()),
    reason="postgres or redis not reachable",
)
@pytest.mark.asyncio
async def test_expired_session_falls_through_to_ip(app_with_db, fresh_ip):
    """A session_id cookie pointing to a non-existent (or expired+cleaned)
    session row SHALL be treated as no session — the IP path runs."""
    bogus_token = "bogus-" + uuid.uuid4().hex

    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/probe",
            cookies={"session_id": bogus_token},
            headers={"x-forwarded-for": fresh_ip},
        )
    assert resp.status_code == 200
    assert resp.json() == {"email": None}

    r = _get_redis()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert int(r.get(f"{KEY_PREFIX}:{fresh_ip}:{today}")) == 1
