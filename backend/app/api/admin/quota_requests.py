"""Admin quota request management endpoints."""
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.quota_request import QuotaRequest, QuotaRequestStatus
from app.models.user import User
from app.schemas.errors import ErrorCode, ErrorResponse
from app.schemas.quota_request import (
    QuotaApprove,
    QuotaApproveResponse,
    QuotaReject,
    QuotaRejectResponse,
    QuotaRequestAdminOut,
)

# require_admin is applied at the parent router level (app.api.admin.__init__).
# We re-declare here on individual mutating endpoints so we have the admin User
# object to record processed_by.
router = APIRouter(prefix="/quota-requests", tags=["admin-quota-requests"])

QUOTA_CEILING = 1_000_000


@router.get("", response_model=list[QuotaRequestAdminOut])
async def list_quota_requests(
    status: Literal["pending", "approved", "rejected"] = Query(default="pending"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(QuotaRequest, User.email, User.quota_remaining)
        .join(User, User.id == QuotaRequest.user_id)
        .where(QuotaRequest.status == status)
        .order_by(QuotaRequest.requested_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    out: list[dict] = []
    for qr, email, quota_remaining in rows:
        out.append(
            {
                "id": qr.id,
                "user_id": qr.user_id,
                "user_email": email,
                "user_quota_remaining": quota_remaining,
                "status": qr.status,
                "reason": qr.reason,
                "requested_at": qr.requested_at,
                "processed_at": qr.processed_at,
                "granted_amount": qr.granted_amount,
                "rejection_note": qr.rejection_note,
                "processed_by": qr.processed_by,
            }
        )
    return out


def _already_processed_error() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=ErrorResponse(
            error_code=ErrorCode.QUOTA_REQUEST_ALREADY_PROCESSED,
            provider=None,
            detail="This quota request has already been processed",
        ).model_dump(),
    )


async def _load_pending_for_update(
    db: AsyncSession, request_id: uuid.UUID
) -> QuotaRequest:
    stmt = (
        select(QuotaRequest)
        .where(QuotaRequest.id == request_id)
        .with_for_update()
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Quota request not found")
    if row.status != QuotaRequestStatus.pending.value:
        raise _already_processed_error()
    return row


@router.post("/{request_id}/approve", response_model=QuotaApproveResponse)
async def approve_quota_request(
    request_id: uuid.UUID,
    payload: QuotaApprove,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> QuotaApproveResponse:
    qr = await _load_pending_for_update(db, request_id)

    user = (
        await db.execute(
            select(User).where(User.id == qr.user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Requester user not found")

    new_quota = min(user.quota_remaining + payload.amount, QUOTA_CEILING)
    user.quota_remaining = new_quota

    qr.status = QuotaRequestStatus.approved.value
    qr.granted_amount = payload.amount
    qr.processed_at = datetime.now(timezone.utc)
    qr.processed_by = admin.id

    await db.commit()
    return QuotaApproveResponse(
        request_id=qr.id, status=qr.status, quota_remaining=new_quota
    )


@router.post("/{request_id}/reject", response_model=QuotaRejectResponse)
async def reject_quota_request(
    request_id: uuid.UUID,
    payload: QuotaReject,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> QuotaRejectResponse:
    qr = await _load_pending_for_update(db, request_id)
    qr.status = QuotaRequestStatus.rejected.value
    qr.rejection_note = payload.note
    qr.processed_at = datetime.now(timezone.utc)
    qr.processed_by = admin.id
    await db.commit()
    return QuotaRejectResponse(request_id=qr.id, status=qr.status)
