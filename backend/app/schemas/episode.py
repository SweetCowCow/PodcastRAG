import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EpisodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    show_id: uuid.UUID
    title: str
    description: str | None
    audio_url: str
    duration_seconds: float | None
    published_at: datetime | None
    guid: str
    created_at: datetime
