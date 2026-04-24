import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl


class ShowCreate(BaseModel):
    rss_url: HttpUrl


class ShowBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    rss_url: str
    image_url: str | None
    language: str | None
    created_at: datetime


class ShowResponse(ShowBase):
    episode_count: int


class ShowListItem(ShowBase):
    episode_count: int
    transcribed_count: int


class RssPreviewResponse(BaseModel):
    title: str
    episode_count: int
    latest_published_at: str | None
