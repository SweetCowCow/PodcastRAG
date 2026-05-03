from pydantic import BaseModel


class QueueStatusResponse(BaseModel):
    active: int
    pending_in_queue: int
    pending_in_db: int
    max_concurrent: int
