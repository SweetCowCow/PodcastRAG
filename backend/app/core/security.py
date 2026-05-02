import hashlib
import hmac
import secrets

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User, UserRole, UserStatus
from app.schemas.errors import ErrorCode, ErrorResponse


def generate_token(num_bytes: int = 32) -> str:
    """Return a URL-safe random token."""
    return secrets.token_urlsafe(num_bytes)


def hash_token(token: str) -> str:
    """Return lowercase SHA-256 hex digest of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


SESSION_COOKIE = "session_id"
CSRF_COOKIE = "csrf_token"


def _err(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(
            error_code=code, provider=None, detail=detail
        ).model_dump(),
    )


async def require_authenticated_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    # Lazy import to avoid circular dependency with services that may import core.
    from app.services.session_service import resolve_session
    from sqlalchemy import select

    if not session_id:
        raise _err(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.NOT_AUTHENTICATED,
            "Not authenticated",
        )

    session_row = await resolve_session(db, session_id)
    if session_row is None:
        raise _err(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.NOT_AUTHENTICATED,
            "Not authenticated",
        )

    result = await db.execute(select(User).where(User.id == session_row.user_id))
    user = result.scalar_one_or_none()
    if user is None or user.status == UserStatus.disabled.value:
        raise _err(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.NOT_AUTHENTICATED,
            "Not authenticated",
        )

    # stash on request for downstream use (e.g., admin user_management self-delete)
    request.state.current_user = user
    return user


async def require_admin(
    user: User = Depends(require_authenticated_user),
) -> User:
    if user.role != UserRole.admin.value or user.status != UserStatus.active.value:
        raise _err(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.FORBIDDEN,
            "Admin role required",
        )
    return user
