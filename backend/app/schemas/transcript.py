import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TranscriptSegmentResponse(BaseModel):
    id: uuid.UUID
    start_time: float
    end_time: float
    text: str
    speaker: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TranscriptResponse(BaseModel):
    id: uuid.UUID
    episode_id: uuid.UUID
    status: str
    language: str | None = None
    transcribed_at: datetime | None = None
    error_message: str | None = None
    segments: list[TranscriptSegmentResponse]


class TranscriptQueuedResponse(BaseModel):
    transcript_id: uuid.UUID
    status: str
    queued_at: datetime


class BatchTranscribeResponse(BaseModel):
    queued: int
