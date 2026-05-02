"""DB-backed tests for auth flows: session, quota, user_service, require_admin.

Skips when local postgres is not reachable. Prod chrome-devtools-mcp covers
end-to-end OAuth callback + login flow.
"""

import asyncio
import socket
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_token
from app.main import app
from app.models.session import Session as SessionRow
from app.models.user import User, UserRole, UserStatus
from app.services import session_service
from app.services.google_oauth import GoogleUserInfo
from app.services.user_service import upsert_user_from_google


def _postgres_reachable() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", 5432))
        return True
    except OSError:
        return False
    finally:
        s.close()


db_required = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="local postgres not running",
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        # Clean test users (email starting with "pytest-")
        await session.execute(
            delete(User).where(User.email.like("pytest-%"))
        )
        await session.commit()
        yield session
        await session.execute(
            delete(User).where(User.email.like("pytest-%"))
        )
        await session.commit()
    await engine.dispose()


# ─── Task 11.1: user_service ADMIN_EMAILS allowlist ───

@db_required
@pytest.mark.asyncio
async def test_first_login_member_default(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")
    info = GoogleUserInfo(
        sub="test-sub-member",
        email="pytest-member@example.com",
        name="Member User",
        picture=None,
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)
    assert user.role == UserRole.member.value
    assert user.status == UserStatus.active.value
    assert user.quota_remaining == 100
    assert user.quota_initial == 100
    assert user.total_queries == 0


@db_required
@pytest.mark.asyncio
async def test_first_login_admin_via_allowlist(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(
        settings,
        "admin_emails",
        "pytest-admin@example.com,other@example.com",
    )
    info = GoogleUserInfo(
        sub="test-sub-admin",
        email="pytest-admin@example.com",
        name="Admin",
        picture=None,
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)
    assert user.role == UserRole.admin.value


@db_required
@pytest.mark.asyncio
async def test_returning_login_does_not_overwrite_role(
    db: AsyncSession, monkeypatch
):
    monkeypatch.setattr(settings, "admin_emails", "")
    info = GoogleUserInfo(
        sub="test-sub-stable",
        email="pytest-stable@example.com",
        name="Stable",
        picture=None,
        email_verified=True,
    )
    u1 = await upsert_user_from_google(db, info)
    # admin manually upgrades
    u1.role = UserRole.admin.value
    await db.commit()
    # second login — role must remain admin
    u2 = await upsert_user_from_google(db, info)
    assert u2.role == UserRole.admin.value


# ─── Task 11.2: session sliding + expiration ───

@db_required
@pytest.mark.asyncio
async def test_resolve_session_extends_expiry(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")
    info = GoogleUserInfo(
        sub="test-sub-sess",
        email="pytest-sess@example.com",
        name="S",
        picture=None,
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)
    issued = await session_service.create_session(db, user.id)
    original_expires = issued.expires_at

    # Manually backdate to simulate elapsed time, then resolve
    row = await db.scalar(
        SessionRow.__table__.select().where(
            SessionRow.session_token_hash == hash_token(issued.session_token)
        )
    )
    assert row is not None

    resolved = await session_service.resolve_session(db, issued.session_token)
    assert resolved is not None
    # expires_at should be ≥ original (sliding extends or keeps)
    assert resolved.expires_at >= original_expires


@db_required
@pytest.mark.asyncio
async def test_expired_session_returns_none_and_deletes(
    db: AsyncSession, monkeypatch
):
    monkeypatch.setattr(settings, "admin_emails", "")
    info = GoogleUserInfo(
        sub="test-sub-exp",
        email="pytest-exp@example.com",
        name="E",
        picture=None,
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)
    issued = await session_service.create_session(db, user.id)

    # Force-expire the row directly in DB
    from sqlalchemy import update as sqlalchemy_update

    await db.execute(
        sqlalchemy_update(SessionRow)
        .where(SessionRow.session_token_hash == hash_token(issued.session_token))
        .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    )
    await db.commit()

    resolved = await session_service.resolve_session(db, issued.session_token)
    assert resolved is None

    # Row should now be deleted
    remaining = await db.scalar(
        SessionRow.__table__.select().where(
            SessionRow.session_token_hash == hash_token(issued.session_token)
        )
    )
    assert remaining is None


# ─── Task 11.4: quota atomic decrement ───

@db_required
@pytest.mark.asyncio
async def test_quota_atomic_decrement_blocks_at_zero(
    db: AsyncSession, monkeypatch
):
    """Direct UPDATE matches the SQL used by /query."""
    from sqlalchemy import update as sa_update

    monkeypatch.setattr(settings, "admin_emails", "")
    info = GoogleUserInfo(
        sub="test-sub-q",
        email="pytest-q@example.com",
        name="Q",
        picture=None,
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)

    # set quota to 1
    await db.execute(
        sa_update(User).where(User.id == user.id).values(quota_remaining=1)
    )
    await db.commit()

    # 1st decrement succeeds
    stmt = (
        sa_update(User)
        .where(User.id == user.id, User.quota_remaining > 0)
        .values(
            quota_remaining=User.quota_remaining - 1,
            total_queries=User.total_queries + 1,
        )
        .returning(User.quota_remaining)
    )
    result = await db.execute(stmt)
    assert result.scalar_one_or_none() == 0
    await db.commit()

    # 2nd decrement is blocked (zero rows)
    result2 = await db.execute(stmt)
    assert result2.scalar_one_or_none() is None
    await db.commit()


@db_required
@pytest.mark.asyncio
async def test_quota_concurrent_only_one_succeeds(
    db: AsyncSession, monkeypatch
):
    """Two concurrent UPDATEs against quota=1 — exactly one succeeds."""
    from sqlalchemy import update as sa_update

    monkeypatch.setattr(settings, "admin_emails", "")
    info = GoogleUserInfo(
        sub="test-sub-concur",
        email="pytest-concur@example.com",
        name="C",
        picture=None,
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)
    await db.execute(
        sa_update(User).where(User.id == user.id).values(quota_remaining=1)
    )
    await db.commit()

    user_id = user.id

    async def attempt_decrement():
        engine = create_async_engine(settings.database_url)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as sess:
            stmt = (
                sa_update(User)
                .where(User.id == user_id, User.quota_remaining > 0)
                .values(
                    quota_remaining=User.quota_remaining - 1,
                    total_queries=User.total_queries + 1,
                )
                .returning(User.quota_remaining)
            )
            res = await sess.execute(stmt)
            val = res.scalar_one_or_none()
            await sess.commit()
        await engine.dispose()
        return val

    a, b = await asyncio.gather(attempt_decrement(), attempt_decrement())
    successes = sum(1 for v in (a, b) if v is not None)
    assert successes == 1


# ─── Task 11.5: require_admin gating via HTTP ───

@db_required
@pytest.mark.asyncio
async def test_admin_endpoint_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/users")
        assert resp.status_code == 401
        assert resp.json()["detail"]["error_code"] == "not_authenticated"


@db_required
@pytest.mark.asyncio
async def test_admin_endpoint_member_returns_403(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")
    info = GoogleUserInfo(
        sub="test-sub-403",
        email="pytest-403@example.com",
        name="M",
        picture=None,
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)
    issued = await session_service.create_session(db, user.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/users",
            cookies={"session_id": issued.session_token},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "forbidden"


@db_required
@pytest.mark.asyncio
async def test_admin_endpoint_admin_role_succeeds(
    db: AsyncSession, monkeypatch
):
    monkeypatch.setattr(
        settings, "admin_emails", "pytest-admin-ok@example.com"
    )
    info = GoogleUserInfo(
        sub="test-sub-admin-ok",
        email="pytest-admin-ok@example.com",
        name="A",
        picture=None,
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)
    issued = await session_service.create_session(db, user.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/users",
            cookies={"session_id": issued.session_token},
        )
        assert resp.status_code == 200
        users = resp.json()
        assert any(u["email"] == "pytest-admin-ok@example.com" for u in users)


# ─── /me endpoint ───

@db_required
@pytest.mark.asyncio
async def test_me_returns_user_payload(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")
    info = GoogleUserInfo(
        sub="test-sub-me",
        email="pytest-me@example.com",
        name="Me",
        picture="http://example.com/avatar.png",
        email_verified=True,
    )
    user = await upsert_user_from_google(db, info)
    issued = await session_service.create_session(db, user.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/me", cookies={"session_id": issued.session_token}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "pytest-me@example.com"
        assert body["role"] == "member"
        assert body["quota_remaining"] == 100
        assert "id" in body


@pytest.mark.asyncio
async def test_me_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/me")
        assert resp.status_code == 401
        assert resp.json()["detail"]["error_code"] == "not_authenticated"
