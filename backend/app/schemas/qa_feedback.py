import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QAFeedbackCreate(BaseModel):
    query_id: str = Field(min_length=1, max_length=64)
    vote: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


class QAFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vote: str
    created_at: datetime


class QAFeedbackStats(BaseModel):
    up_7d: int
    down_7d: int
    total_7d: int
    ratio: float | None
