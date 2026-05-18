"""POST /auth/appeal endpoint tests.

Covers:
- disabled user → 200 with appeal_id + DB row written
- unknown email → 200 silent-drop, no row
- active user → 200 silent-drop, no row
- empty / oversize reason → 400 invalid_reason
- per-IP rate limit: 6th submission → 429 rate_limited

Uses a FastAPI dependency override + in-memory async SQLite session so the
tests don't depend on the dev postgres being reachable from the test
process (which is the pre-existing baseline failure mode for many other
DB-backed tests in this repo).
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.account_appeal import AccountAppeal  # noqa: F401 — ensure metadata registered
from app.models.user import User, UserStatus


@pytest_asyncio.fixture
async def db_engine():
    """In-memory aiosqlite engine seeded with required tables (users +
    account_appeals). We register only those tables to avoid pulling in
    pgvector / TSVECTOR types that aiosqlite can't compile."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        # Only create the two tables we exercise — full metadata.create_all()
        # fails on pgvector / TSVECTOR columns under SQLite.
        from app.models.account_appeal import AccountAppeal as _AA
        from app.models.user import User as _U
        await conn.run_sync(lambda c: _U.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: _AA.__table__.create(c, checkfirst=True))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(db_session_maker, monkeypatch):
    """AsyncClient wired to a FastAPI app whose get_db yields our test session.
    Also stubs the rate-limit helper to never block (rate-limit test
    monkeypatches it separately)."""
    from app.api import appeal as appeal_mod

    async def _override_get_db():
        async with db_session_maker() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db

    def _no_limit(_ip):
        return (1, False)

    monkeypatch.setattr(appeal_mod, "_check_appeal_rate", _no_limit)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)


async def _seed_user(session_maker, *, email: str, status: str):
    async with session_maker() as db:
        user = User(
            email=email,
            name="test",
            provider="google",
            google_sub=f"sub-{uuid.uuid4().hex[:12]}",
            role="member",
            status=status,
            quota_remaining=30,
            quota_initial=30,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_disabled_user_accepted(client, db_session_maker):
    email = "disabled@example.com"
    await _seed_user(db_session_maker, email=email, status=UserStatus.disabled.value)

    res = await client.post(
        "/auth/appeal",
        json={"email": email, "reason": "我覺得被誤判停權"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] is True
    assert body.get("appeal_id")

    # Row written
    from sqlalchemy import select
    async with db_session_maker() as db:
        rows = list((await db.execute(
            select(AccountAppeal).where(AccountAppeal.email == email)
        )).scalars().all())
        assert len(rows) == 1
        assert rows[0].reason == "我覺得被誤判停權"


@pytest.mark.asyncio
async def test_unknown_email_silent_drop(client, db_session_maker):
    res = await client.post(
        "/auth/appeal",
        json={"email": "nobody@nowhere.com", "reason": "test reason text"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] is True
    assert body.get("appeal_id") is None

    from sqlalchemy import select
    async with db_session_maker() as db:
        rows = list((await db.execute(select(AccountAppeal))).scalars().all())
        assert rows == []


@pytest.mark.asyncio
async def test_active_user_silent_drop(client, db_session_maker):
    email = "active@example.com"
    await _seed_user(db_session_maker, email=email, status=UserStatus.active.value)

    res = await client.post(
        "/auth/appeal",
        json={"email": email, "reason": "active user trying"},
    )
    assert res.status_code == 200
    assert res.json().get("appeal_id") is None

    from sqlalchemy import select
    async with db_session_maker() as db:
        rows = list((await db.execute(select(AccountAppeal))).scalars().all())
        assert rows == []


@pytest.mark.asyncio
async def test_invalid_reason_rejected(client):
    # Empty
    res = await client.post(
        "/auth/appeal",
        json={"email": "anyone@example.com", "reason": ""},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "invalid_reason"

    # Oversize
    res2 = await client.post(
        "/auth/appeal",
        json={"email": "anyone@example.com", "reason": "x" * 2001},
    )
    assert res2.status_code == 400
    assert res2.json()["detail"]["error_code"] == "invalid_reason"


@pytest.mark.asyncio
async def test_rate_limit_6th_request_blocked(db_session_maker, monkeypatch):
    """5 succeed (200 silent-drop), 6th → 429 rate_limited."""
    from app.api import appeal as appeal_mod

    async def _override_get_db():
        async with db_session_maker() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db

    counter = {"n": 0}

    def fake_check(_ip):
        counter["n"] += 1
        return counter["n"], counter["n"] > 5

    monkeypatch.setattr(appeal_mod, "_check_appeal_rate", fake_check)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            for i in range(5):
                res = await ac.post(
                    "/auth/appeal",
                    json={"email": "x@example.com", "reason": f"attempt {i}"},
                )
                assert res.status_code == 200, f"attempt {i}: {res.status_code}"

            res6 = await ac.post(
                "/auth/appeal",
                json={"email": "x@example.com", "reason": "attempt 6"},
            )
            assert res6.status_code == 429
            assert res6.json()["detail"]["error_code"] == "rate_limited"
    finally:
        app.dependency_overrides.pop(get_db, None)
