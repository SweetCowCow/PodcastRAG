from pydantic import BaseModel


class PublicStatsResponse(BaseModel):
    """Public-safe stats — no user count."""

    episodes_completed: int
    transcript_chunks: int
    shows: int


class StatsResponse(PublicStatsResponse):
    """Admin view — adds users count."""

    users: int
