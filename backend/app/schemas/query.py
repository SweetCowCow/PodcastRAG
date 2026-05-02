import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class QueryRequest(BaseModel):
    mode: Literal["chat", "search"]
    question: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(default_factory=list)


class ChunkHit(BaseModel):
    episode_id: uuid.UUID
    episode_title: str
    start_time: float
    end_time: float
    text: str
    distance: float | None = None


class SearchResponse(BaseModel):
    results: list[ChunkHit]
    quota_remaining: int


class ChatResponse(BaseModel):
    answer: str
    citations: list[ChunkHit]
    quota_remaining: int
