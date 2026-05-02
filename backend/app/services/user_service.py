from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole, UserStatus
from app.services.google_oauth import GoogleUserInfo


async def upsert_user_from_google(
    db: AsyncSession, info: GoogleUserInfo
) -> User:
    """Find user by google_sub or email; insert if missing.

    First-time admin allowlist check applies on insert only — existing rows
    keep their role/status untouched (admin can override via UI later).
    """
    result = await db.execute(select(User).where(User.google_sub == info.sub))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        # fallback: match by email (e.g., user pre-provisioned with same email)
        result = await db.execute(select(User).where(User.email == info.email))
        user = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if user is None:
        is_admin = info.email.lower() in settings.admin_email_set
        user = User(
            email=info.email,
            name=info.name,
            avatar_url=info.picture,
            provider="google",
            google_sub=info.sub,
            role=UserRole.admin.value if is_admin else UserRole.member.value,
            status=UserStatus.active.value,
            quota_remaining=100,
            quota_initial=100,
            total_queries=0,
            last_login_at=now,
        )
        db.add(user)
        await db.flush()
    else:
        # Existing user: refresh profile fields and last_login_at,
        # but never overwrite role/status.
        if user.google_sub is None:
            user.google_sub = info.sub
        user.name = info.name or user.name
        user.avatar_url = info.picture or user.avatar_url
        user.last_login_at = now

    await db.commit()
    await db.refresh(user)
    return user
