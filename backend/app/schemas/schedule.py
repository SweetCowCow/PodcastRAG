import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.show_schedule import RefreshStatus


class ScheduleUpsert(BaseModel):
    """Payload for PUT /shows/{show_id}/schedule.

    ``max_episodes_per_run`` is REQUIRED (≥ 1) per the
    transcription-schedule capability — every upsert must specify it.
    """

    enabled: bool | None = None
    frequency: str | None = None
    run_time: str | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    whisper_model: str | None = None
    max_episodes_per_run: int = Field(..., ge=1)


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    show_id: uuid.UUID
    enabled: bool
    frequency: str
    run_time: str
    day_of_week: int
    whisper_model: str
    max_episodes_per_run: int
    last_refresh_at: datetime | None
    last_refresh_status: RefreshStatus
    last_refresh_message: str | None
    created_at: datetime
    updated_at: datetime


class AdminScheduleItem(BaseModel):
    show_id: uuid.UUID
    show_title: str
    rss_url: str
    schedule: ScheduleResponse | None
    pending_count: int
    last_transcribed_at: datetime | None
