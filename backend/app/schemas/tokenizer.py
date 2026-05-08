import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TokenizerTermCreate(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    weight: int = Field(default=100, ge=1)
    is_show_name: bool = False


class TokenizerTermPatch(BaseModel):
    is_show_name: bool


class TokenizerTermResponse(BaseModel):
    id: uuid.UUID
    term: str
    weight: int
    source: str
    is_show_name: bool = False
    created_at: datetime
    created_by_user_id: uuid.UUID | None = None
