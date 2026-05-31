"""Request / response schemas for the keyword (索引) search endpoint.

Shape mirrors `openspec/changes/keyword-index-mode/design.md` → "Response
Schema". The `collapsed` presentation hint lives on T2 only.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class KeywordSearchRequest(BaseModel):
    query: str
    offset_t1: int = Field(default=0, ge=0)
    offset_t2: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=100)


class TermHit(BaseModel):
    term: str
    positions: list[int] = Field(default_factory=list)


class PoolCounts(BaseModel):
    title: int = 0
    description: int = 0
    transcript: int = 0


class T1Hit(BaseModel):
    chunk_id: uuid.UUID
    episode_id: uuid.UUID
    episode_title: str
    start_time: float
    end_time: float
    text: str
    hits: list[TermHit] = Field(default_factory=list)


class T2Hit(BaseModel):
    episode_id: uuid.UUID
    episode_title: str
    pool_counts: PoolCounts


class T3Hit(BaseModel):
    chunk_id: uuid.UUID
    episode_id: uuid.UUID
    episode_title: str
    start_time: float
    end_time: float
    text: str
    hits: list[TermHit] = Field(default_factory=list)


class T1Section(BaseModel):
    section: str = "chunk-and"
    total: int = 0
    items: list[T1Hit] = Field(default_factory=list)


class T2Section(BaseModel):
    section: str = "episode-and"
    total: int = 0
    collapsed: bool = False
    items: list[T2Hit] = Field(default_factory=list)


class T3Section(BaseModel):
    section: str = "or-fallback"
    total: int = 0
    items: list[T3Hit] = Field(default_factory=list)


class KeywordSearchResponse(BaseModel):
    query: str
    terms: list[str] = Field(default_factory=list)
    mode: str = "keyword"
    t1: T1Section
    t2: T2Section
    t3: T3Section | None = None
