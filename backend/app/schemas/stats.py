from pydantic import BaseModel


class StatsResponse(BaseModel):
    episodes_completed: int
    transcript_chunks: int
    shows: int
    users: int
