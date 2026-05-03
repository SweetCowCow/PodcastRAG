import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_token, hash_token
from app.models.session import Session as SessionRow


def derive_csrf_token(session_token: str) -> str:
    """Derive CSRF token from session token via HMAC-SHA256.

    This avoids needing to store the CSRF token separately and avoids
    the cross-origin cookie-read problem (frontend on a different
    subdomain cannot read cookies set by the backend). Frontend gets
    the token from /me response body and echoes it as X-CSRF-Token.
    """
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass
class IssuedSession:
    """Returned to the auth router so it can set cookies."""

    session_token: str  # raw, goes into session_id cookie (httpOnly)
    csrf_token: str  # raw, goes into csrf_token cookie (JS-readable)
    user_id: uuid.UUID
    expires_at: datetime


async def create_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    ip: str | None = None,
    user_agent: str | None = None,
    ttl_override: timedelta | None = None,
) -> IssuedSession:
    session_token = generate_token(32)
    csrf_token = generate_token(32)
    now = datetime.now(timezone.utc)
    expires_at = now + (ttl_override or timedelta(days=settings.session_ttl_days))

    row = SessionRow(
        user_id=user_id,
        session_token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=expires_at,
        last_seen_at=now,
        ip=ip,
        user_agent=user_agent,
    )
    db.add(row)
    await db.commit()

    return IssuedSession(
        session_token=session_token,
        csrf_token=csrf_token,
        user_id=user_id,
        expires_at=expires_at,
    )


async def resolve_session(
    db: AsyncSession, session_token: str
) -> SessionRow | None:
    """Resolve session, sliding-extend expires_at, or delete if expired."""
    token_hash = hash_token(session_token)
    result = await db.execute(
        select(SessionRow).where(SessionRow.session_token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        await db.delete(row)
        await db.commit()
        return None

    row.last_seen_at = now
    row.expires_at = now + timedelta(days=settings.session_ttl_days)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_session(db: AsyncSession, session_token: str) -> None:
    token_hash = hash_token(session_token)
    await db.execute(
        delete(SessionRow).where(SessionRow.session_token_hash == token_hash)
    )
    await db.commit()


async def verify_csrf_token(
    db: AsyncSession, session_token: str, csrf_token_from_header: str
) -> bool:
    """Used by middleware: verify CSRF header matches session row's csrf_token_hash."""
    if not csrf_token_from_header:
        return False
    expected_hash = hash_token(csrf_token_from_header)
    actual_token_hash = hash_token(session_token)
    result = await db.execute(
        select(SessionRow.csrf_token_hash).where(
            SessionRow.session_token_hash == actual_token_hash
        )
    )
    stored_hash = result.scalar_one_or_none()
    if stored_hash is None:
        return False
    # constant-time compare via hmac
    import hmac as _hmac

    return _hmac.compare_digest(stored_hash, expected_hash)
