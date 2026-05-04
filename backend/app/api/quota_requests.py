"""User-facing quota request endpoints.

Authenticated users can submit a request for additional quota and view their
own request history. The admin counterpart lives in app/api/admin/quota_requests.py.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_authenticated_user
from app.models.quota_request import QuotaRequest, QuotaRequestStatus
from app.models.user import User
from app.schemas.errors import ErrorCode, ErrorResponse
from app.schemas.quota_request import QuotaRequestCreate, QuotaRequestOut

router = APIRouter(prefix="/quota-requests", tags=["quota-requests"])


@router.post("", response_model=QuotaRequestOut, status_code=201)
async def submit_quota_request(
    payload: QuotaRequestCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
) -> QuotaRequest:
    """Create a new pending quota request. Rejects with 409 if the user
    already has a pending row (one outstanding request at a time)."""
    existing = (
        await db.execute(
            select(QuotaRequest.id).where(
                QuotaRequest.user_id == user.id,
                QuotaRequest.status == QuotaRequestStatus.pending.value,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error_code=ErrorCode.QUOTA_REQUEST_PENDING,
                provider=None,
                detail="You already have a pending quota request",
            ).model_dump(),
        )

    row = QuotaRequest(
        user_id=user.id,
        reason=payload.reason,
        status=QuotaRequestStatus.pending.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/me", response_model=list[QuotaRequestOut])
async def list_my_quota_requests(
    status: Literal["pending", "approved", "rejected"] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
) -> list[QuotaRequest]:
    stmt = select(QuotaRequest).where(QuotaRequest.user_id == user.id)
    if status is not None:
        stmt = stmt.where(QuotaRequest.status == status)
    stmt = stmt.order_by(QuotaRequest.requested_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
