import os
import secrets
import socket
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/podcastrag",
)
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:8080")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
)
os.environ.setdefault(
    "SESSION_SECRET", "test-session-secret-do-not-use-in-prod-thirtytwo+chars"
)
os.environ.setdefault("ADMIN_EMAILS", "")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)


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


# ─── Auth helpers / fixtures ───
# Build admin / member users with valid sessions so existing admin endpoint
# tests can pass real cookies + CSRF headers. Each fixture seeds rows in the
# test database and cleans them up afterwards.

CSRF_ORIGIN = "http://localhost:8080"


async def _seed_user(db, *, role: str, status: str = "active"):
    from app.models.user import User

    suffix = secrets.token_hex(4)
    user = User(
        email=f"pytest-{role}-{suffix}@example.com",
        name=f"pytest {role}",
        provider="google",
        google_sub=f"google-sub-{suffix}",
        role=role,
        status=status,
        quota_remaining=100,
        quota_initial=100,
        total_queries=0,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _seed_session(db, user_id: uuid.UUID) -> str:
    """Create a session row, return raw session token for cookie use."""
    from app.core.security import hash_token
    from app.models.session import Session as SessionRow

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    row = SessionRow(
        user_id=user_id,
        session_token_hash=hash_token(token),
        csrf_token_hash="unused",  # post-CSRF-fix: middleware derives CSRF from session token
        expires_at=now + timedelta(days=1),
        last_seen_at=now,
    )
    db.add(row)
    await db.commit()
    return token


def csrf_headers(session_token: str) -> dict:
    """Headers needed for state-changing requests in tests."""
    from app.services.session_service import derive_csrf_token

    return {
        "X-CSRF-Token": derive_csrf_token(session_token),
        "Origin": CSRF_ORIGIN,
    }


@pytest_asyncio.fixture
async def db_session():
    """Yield an AsyncSession bound to the dev database; cleans test rows after."""
    from app.core.config import settings
    from app.models.user import User

    engine = create_async_engine(settings.database_url)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with Maker() as session:
        await session.execute(delete(User).where(User.email.like("pytest-%")))
        await session.commit()
        yield session
        await session.execute(delete(User).where(User.email.like("pytest-%")))
        await session.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def auth_admin(db_session):
    """Yield (admin_user, session_token, cookies dict, csrf headers dict)."""
    user = await _seed_user(db_session, role="admin")
    token = await _seed_session(db_session, user.id)
    yield {
        "user": user,
        "session_token": token,
        "cookies": {"session_id": token},
        "csrf_headers": csrf_headers(token),
    }


@pytest_asyncio.fixture
async def auth_member(db_session):
    user = await _seed_user(db_session, role="member")
    token = await _seed_session(db_session, user.id)
    yield {
        "user": user,
        "session_token": token,
        "cookies": {"session_id": token},
        "csrf_headers": csrf_headers(token),
    }


# Re-export for tests that want it
__all__ = [
    "_postgres_reachable",
    "csrf_headers",
    "auth_admin",
    "auth_member",
    "db_session",
]
