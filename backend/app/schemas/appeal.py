"""Pydantic schemas for POST /auth/appeal.

Empty/oversize ``reason`` raises ValidationError → FastAPI returns 400 with
``error_code=invalid_reason`` (mapped via a custom validator + handler).
"""
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


REASON_MIN = 1
REASON_MAX = 2000


class AppealRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    # Plain str (not EmailStr) — we don't want a hard dependency on
    # email-validator, and the value is matched against users.email exactly
    # so any non-matching string silent-drops anyway.
    email: str = Field(..., min_length=3, max_length=320)
    reason: str = Field(..., min_length=REASON_MIN, max_length=REASON_MAX)

    @field_validator("email")
    @classmethod
    def _email_basic_shape(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("email must contain @")
        return v

    @field_validator("reason")
    @classmethod
    def _strip_must_be_non_empty(cls, v: str) -> str:
        if v is None or not v.strip():
            raise ValueError("reason must be non-empty after trim")
        if len(v) > REASON_MAX:
            raise ValueError(f"reason exceeds {REASON_MAX} chars")
        return v


class AppealResponse(BaseModel):
    accepted: bool = True
    appeal_id: uuid.UUID | None = None
