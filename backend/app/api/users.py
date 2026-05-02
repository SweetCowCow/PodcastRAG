"""Admin user management endpoints (require admin role)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.user import User
from app.schemas.errors import ErrorCode, ErrorResponse
from app.schemas.user import QuotaPatch, UserAdminOut, UserAdminUpdate

router = APIRouter(
    prefix="/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(require_admin)],
)

QUOTA_MIN = 0
QUOTA_MAX = 1_000_000


@router.get("", response_model=list[UserAdminOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserAdminOut]:
    """Return all users, ordered by last_login_at DESC NULLS LAST, then created_at DESC."""
    result = await db.execute(
        select(User).order_by(
            User.last_login_at.desc().nullslast(), User.created_at.desc()
        )
    )
    users = result.scalars().all()
    return [UserAdminOut.model_validate(u) for u in users]


@router.patch("/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
) -> UserAdminOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(user, k, v)
    await db.commit()
    await db.refresh(user)
    return UserAdminOut.model_validate(user)


@router.patch("/{user_id}/quota", response_model=dict)
async def patch_quota(
    user_id: uuid.UUID,
    payload: QuotaPatch,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Adjust quota_remaining by delta. Result clamped to [0, 1_000_000]."""
    # Use SQL GREATEST/LEAST for atomic clamping
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(
            quota_remaining=func_clamp(User.quota_remaining + payload.delta)
        )
        .returning(User.quota_remaining)
    )
    result = await db.execute(stmt)
    new_remaining = result.scalar_one_or_none()
    await db.commit()
    if new_remaining is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"quota_remaining": int(new_remaining)}


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error_code=ErrorCode.FORBIDDEN,
                provider=None,
                detail="Cannot delete your own account",
            ).model_dump(),
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await db.delete(user)
    await db.commit()
    return None


def func_clamp(expr):
    """Clamp expression to [QUOTA_MIN, QUOTA_MAX] via LEAST/GREATEST."""
    from sqlalchemy import func

    return func.greatest(QUOTA_MIN, func.least(QUOTA_MAX, expr))
