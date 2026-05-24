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
    # chat-agentic-tool-routing: client-provided session UUID keeps L1 state
    # across turns. If omitted, each request starts a fresh session (no carry).
    session_id: uuid.UUID | None = None


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


class ToolCallTrace(BaseModel):
    """Single tool dispatch record produced by the agentic chat loop.

    Populated only when `ENABLE_AGENTIC_CHAT=true` served the request. The
    frontend can render a collapsed trace for debugging / observability.
    """

    name: str
    args: dict
    result_summary: str = Field(max_length=500)
    raised: str | None = None
    latency_ms: float
    # agent-trace-telemetry: full tool result JSON, only populated when the
    # admin debug_trace gate fires (see `Query endpoint exposes trace under
    # admin debug gate`). `None` for default chat responses.
    result_full: str | None = None


class LLMCallTraceResponse(BaseModel):
    """Per-round LLM API call telemetry (admin debug_trace mode only)."""

    round_index: int
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    had_tool_calls: bool


class StageTimingsResponse(BaseModel):
    """Per-stage elapsed-ms timings (admin debug_trace mode only)."""

    build_messages_ms: float
    state_load_ms: float
    state_save_ms: float
    history_summary_ms: float
    llm_loop_total_ms: float


class EnumerationStateSnapshot(BaseModel):
    """State of `ChatSessionState.last_enumeration_episodes` captured at
    `_build_system_message` time for the current turn. Only populated
    under admin debug_trace gate; otherwise omitted.

    Added by agentic-severe-residual-fix-2026-05 to diagnose mt01 t2
    multi-turn ordinal carry failure without altering carry logic.
    """

    last_enumeration_episodes: list[str] = Field(default_factory=list)
    last_enumeration_at: str | None = None
    user_question: str


class AgentTraceResponse(BaseModel):
    """Full agent telemetry trace, returned only under admin debug_trace gate."""

    llm_calls: list[LLMCallTraceResponse] = Field(default_factory=list)
    stage_timings: StageTimingsResponse
    # agentic-severe-residual-fix-2026-05: enumeration state at the
    # moment build_messages composed the turn's system prompt. None
    # when no snapshot was captured (e.g. error path) or non-admin.
    enumeration_state: EnumerationStateSnapshot | None = None


class ChatResponse(BaseModel):
    query_id: str
    answer: str
    citations: list[ChunkHit]
    quota_remaining: int
    citations_meta: list[SentenceCitations] = Field(default_factory=list)
    sources_schema_version: int = SOURCES_SCHEMA_VERSION
    # chat-agentic-tool-routing: populated only when the agent loop served
    # the request (ENABLE_AGENTIC_CHAT=true). `None` / `False` for the
    # rule-based pipeline so the existing response shape is preserved.
    tool_calls: list[ToolCallTrace] | None = None
    agent_truncated: bool = False
    # agentic-severe-residual-fix-2026-05: number of EP-tokens / quoted
    # strings in `answer` that did NOT appear in any tool result this
    # turn (annotated in-place with `[未驗證]` suffix). 0 when no
    # mismatch, or when the agent path was bypassed.
    unverified_count: int = 0
    # R3.3 Phase 9: present only when the query is an enumeration question
    # (entity-driven OR rule-pattern). `None` for non-enumeration queries
    # so the frontend can switch UI mode without inspecting `citations`.
    # Empty list `[]` means "enumeration triggered but no episode matched"
    # (distinct from null = "did not trigger").
    enumeration_episodes: list[EpisodeRef] | None = None
    # r3-3-chat-enum-grounding: full count of episodes the enumeration
    # path matched. Equal to `len(enumeration_episodes)` today (no backend
    # cap); kept as a separate field so future paginated backends can
    # surface "showing X of N" without changing the list shape. `None`
    # mirrors `enumeration_episodes is None` (enum did not trigger).
    enumeration_total: int | None = None
    # agent-trace-telemetry: per-stage timings + per-round LLM calls. Only
    # populated when the request carries `?debug_trace=true` AND the session
    # belongs to an admin user. `None` for all other requests.
    trace: AgentTraceResponse | None = None


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
