import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QuotaRequestCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


class QuotaRequestOut(BaseModel):
    """User-facing view (own requests)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    reason: str
    requested_at: datetime
    processed_at: datetime | None
    granted_amount: int | None
    rejection_note: str | None


class QuotaRequestAdminOut(QuotaRequestOut):
    """Admin-facing view augmented with requester info."""

    user_id: uuid.UUID
    user_email: str
    user_quota_remaining: int
    processed_by: uuid.UUID | None


class QuotaApprove(BaseModel):
    amount: int = Field(ge=1, le=1_000_000)


class QuotaReject(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


class QuotaApproveResponse(BaseModel):
    request_id: uuid.UUID
    status: str
    quota_remaining: int


class QuotaRejectResponse(BaseModel):
    request_id: uuid.UUID
    status: str
