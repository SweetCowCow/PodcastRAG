import uuid
from datetime import datetime

from pydantic import BaseModel


class TranscriptionStatusCounts(BaseModel):
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0


class CurrentlyProcessingItem(BaseModel):
    episode_id: uuid.UUID
    episode_title: str
    started_at: datetime


class RecentFailureItem(BaseModel):
    episode_id: uuid.UUID
    episode_title: str
    error_message: str
    error_category: str | None
    failed_at: datetime


class TranscriptionStatusResponse(BaseModel):
    counts: TranscriptionStatusCounts
    currently_processing: list[CurrentlyProcessingItem]
    recent_failures: list[RecentFailureItem]
