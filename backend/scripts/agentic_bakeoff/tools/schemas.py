"""Pydantic input/output schemas for the 9 tools (11 callables).

Schemas are the LLM-facing contract: framework-agnostic, no DB / Redis types.
Real wiring (DB session, Redis client, show_id, session_id) is passed
separately via `ToolContext` in `context.py`.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


# ---- shared output types ----

class EpisodeRef(BaseModel):
    episode_id: uuid.UUID
    title: str
    published_at: datetime | None = None
    guests: list[str] = Field(default_factory=list)
    ai_summary: str | None = None


class Segment(BaseModel):
    segment_id: int
    start_sec: float
    end_sec: float
    text: str
    topic_label: str | None = None


class ChunkHit(BaseModel):
    chunk_id: uuid.UUID | None  # title hits have None
    episode_id: uuid.UUID
    episode_title: str
    text: str
    rrf_score: float
    pool: str  # transcript / description / title


# ---- 1. find_episode_by_ref ----

class FindEpisodeByRefInput(BaseModel):
    ref: str = Field(description="e.g. 'EP143' / 'Axios 那集' / '上一集'")


class FindEpisodeByRefOutput(BaseModel):
    episode: EpisodeRef | None


# ---- 2. find_episodes_by_guest ----

class FindEpisodesByGuestInput(BaseModel):
    name: str = Field(description="guest name e.g. '馬世芳'")


class EpisodeListOutput(BaseModel):
    episodes: list[EpisodeRef]


# ---- 3. find_episodes_by_topic ----

class FindEpisodesByTopicInput(BaseModel):
    topic: str = Field(description="topic keyword e.g. '歌單'")


# ---- 4. find_episodes_by_date ----

class FindEpisodesByDateInput(BaseModel):
    start: date
    end: date


# ---- 5. get_episode_summary ----

class GetEpisodeSummaryInput(BaseModel):
    episode_id: uuid.UUID


class GetEpisodeSummaryOutput(BaseModel):
    summary: str


# ---- 6. get_episode_segments ----

class GetEpisodeSegmentsInput(BaseModel):
    episode_id: uuid.UUID
    topic_filter: str | None = None


class SegmentListOutput(BaseModel):
    segments: list[Segment]


# ---- 7a. search_within_episode ----

class SearchWithinEpisodeInput(BaseModel):
    query: str
    episode_id: uuid.UUID
    k: int = 5


class ChunkListOutput(BaseModel):
    chunks: list[ChunkHit]


# ---- 7b. search_across_episodes ----

class SearchAcrossEpisodesInput(BaseModel):
    query: str
    k: int = 8


# ---- 7c. search_in_episodes ----

class SearchInEpisodesInput(BaseModel):
    query: str
    episode_ids: list[uuid.UUID]
    k: int = 8


# ---- 8. get_show_overview ----

class GetShowOverviewInput(BaseModel):
    pass  # show_id comes from ToolContext


class GetShowOverviewOutput(BaseModel):
    overview: str


# ---- 9. pin_episode / unpin_episode ----

class PinEpisodeInput(BaseModel):
    episode_id: uuid.UUID


class UnpinEpisodeInput(BaseModel):
    pass


class OkOutput(BaseModel):
    ok: bool
