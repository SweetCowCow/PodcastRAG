import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    """Public payload for /me — what the logged-in user sees about themselves."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None
    avatar_url: str | None
    role: str
    status: str
    total_queries: int
    quota_remaining: int
    quota_initial: int


class UserAdminOut(UserOut):
    """Extra fields visible to admin in user management list."""

    provider: str
    notes: str | None
    created_at: datetime
    last_login_at: datetime | None


class UserAdminUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(admin|member)$")
    status: str | None = Field(default=None, pattern=r"^(active|pending|disabled)$")
    notes: str | None = Field(default=None, max_length=500)


class QuotaPatch(BaseModel):
    delta: int
