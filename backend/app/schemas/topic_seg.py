import uuid

from pydantic import BaseModel


class AuditSampleItem(BaseModel):
    segment_id: uuid.UUID
    episode_id: uuid.UUID
    episode_title: str
    start_time: float
    end_time: float
    text: str
    topic_label: str
    prev_text: str | None = None
    next_text: str | None = None
    is_show_specific_label: bool = False
