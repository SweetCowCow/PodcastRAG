import uuid
from datetime import datetime
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
    source: Literal["transcript", "description", "title"] = "transcript"
    # R2.1 citation infra: extra context fields. Default to empty so older
    # callers that don't pass them still construct a valid model.
    before_text: str = ""
    after_text: str = ""
    highlights: str = ""
    ai_summary_excerpt: str = ""
    # R2.1 followup: full (untruncated) episode ai_summary, used by the
    # frontend SourceCard "expand" toggle. None when the episode has no
    # ai_summary.
    ai_summary_full: str | None = None


# Schema version for the source/citation entry shape. R4 cache should key on
# this value so a future bump invalidates stale entries (see R2.1 design,
# Open Question — `sources_schema_version`).
SOURCES_SCHEMA_VERSION: int = 1


class SentenceCitations(BaseModel):
    """Per-sentence citation metadata produced by the citation parser.

    `sentence_index` is the 0-based index of the sentence in the cleaned
    answer (sentences split on `。 ！ ？ . ! ?`). `ref_ids` is the list of
    valid 1-based source numbers referenced inside that sentence.
    """

    sentence_index: int
    ref_ids: list[int] = Field(default_factory=list)


class SearchResponse(BaseModel):
    results: list[ChunkHit]
    quota_remaining: int
    sources_schema_version: int = SOURCES_SCHEMA_VERSION


class EpisodeRef(BaseModel):
    """Episode-level reference returned by cross-episode enumeration queries.

    R3.3 Phase 9: populated only for chat queries whose entity extractor
    flagged a `guests` / `date_range` constraint, or whose question matched
    the enumeration rule pattern (`哪幾集 / 哪集 / 哪些集`). Carries enough
    fields for the frontend to render a clickable episode card without an
    extra round-trip.
    """

    episode_id: uuid.UUID
    title: str
    published_at: datetime | None = None
    guests: list[str] = Field(default_factory=list)
    ai_summary: str | None = None


class ChatResponse(BaseModel):
    query_id: str
    answer: str
    citations: list[ChunkHit]
    quota_remaining: int
    citations_meta: list[SentenceCitations] = Field(default_factory=list)
    sources_schema_version: int = SOURCES_SCHEMA_VERSION
    # R3.3 Phase 9: present only when the query is an enumeration question
    # (entity-driven OR rule-pattern). `None` for non-enumeration queries
    # so the frontend can switch UI mode without inspecting `citations`.
    enumeration_episodes: list[EpisodeRef] | None = None


class PublicSearchRequest(BaseModel):
    """Body for the public-search endpoint (POST /shows/{id}/search).

    Anonymous and authenticated callers share the same request shape.
    """

    question: str = Field(min_length=1, max_length=500)
    k: int = Field(default=8, ge=1, le=50)


class PublicSearchResponse(BaseModel):
    """Public-search response: top-K segments with no LLM-generated answer.
    Quota counters are not relevant here (no decrement) so the field is omitted.
    """

    results: list[ChunkHit]
    sources_schema_version: int = SOURCES_SCHEMA_VERSION
