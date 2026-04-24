import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ScheduleUpsert(BaseModel):
    enabled: bool | None = None
    frequency: str | None = None
    run_time: str | None = None
    whisper_model: str | None = None
    max_episodes: int | None = None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    show_id: uuid.UUID
    enabled: bool
    frequency: str
    run_time: str
    whisper_model: str
    max_episodes: int
    created_at: datetime
    updated_at: datetime


class AdminScheduleItem(BaseModel):
    show_id: uuid.UUID
    show_title: str
    rss_url: str
    schedule: ScheduleResponse | None
    pending_count: int
    last_transcribed_at: datetime | None
