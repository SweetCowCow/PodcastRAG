"""Tool registry + dispatcher for the chat agent
(chat-agentic-tool-routing change).

11 callables backed by 9 numbered tools (per design.md):

  1.   find_episode_by_ref        → episode_finders.find_by_ref
  2.   find_episodes_by_guest     → episode_finders.find_episodes_by_guest
  3.   find_episodes_by_topic     → episode_finders.find_episodes_by_topic
  4.   find_episodes_by_date      → episode_finders.find_episodes_by_date_range
  5.   get_episode_summary        → episodes.ai_summary column
  6.   get_episode_segments       → transcript_segments table read
  7a.  search_within_episode      → rag.retrieve_hybrid w/ episode_id_filter
  7b.  search_across_episodes     → rag.retrieve_hybrid (no filter)
  7c.  search_in_episodes         → rag.retrieve_hybrid w/ multi-ep filter
  8.   get_show_overview          → shows.description column
  9a.  pin_episode                → write ChatSessionState.focused_episode_id
  9b.  unpin_episode              → clear ChatSessionState.focused_episode_id

OpenAI tool function schemas are derived from the Pydantic input models
via `_pydantic_to_openai_function` — no hand-written JSON Schema.

`_dispatch_tool` catches Pydantic `ValidationError` and any other
Exception, converts them into `{"error": "<class>: <msg>"}` JSON payloads
so the LLM can apologise / retry instead of the request 5xx-ing.

The three enumeration tools (`find_episodes_by_guest/topic/date`)
write their result episode IDs back into
`ChatSessionState.last_enumeration_episodes` (FIFO-capped) — this is
what fixes the multi-turn carry regression bake-off found.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import episode_finders, rag
from app.services.ai_step_resolver import get_step_config
from app.services.chat_agent.state import ChatSessionState, ChatSessionStateStore
from app.services.embedding import embed_texts

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Input schemas (LLM-facing). Output is plain dict the LLM can read.
# ──────────────────────────────────────────────────────────────────────


class FindEpisodeByRefInput(BaseModel):
    ref: str = Field(description="e.g. 'EP143' / 'Axios 那集' / '上一集'")


class FindEpisodesByGuestInput(BaseModel):
    name: str = Field(description="guest name e.g. '馬世芳'")


class FindEpisodesByTopicInput(BaseModel):
    topic: str = Field(description="topic keyword e.g. '歌單'")


class FindEpisodesByDateInput(BaseModel):
    start: date
    end: date
    order: Literal["newest", "oldest"] = "newest"
    limit: int | None = Field(default=None, ge=1, le=50)


class GetEpisodeSummaryInput(BaseModel):
    episode_id: uuid.UUID | None = Field(
        default=None,
        description="Omit to use session focused_episode_id (auto-pinned by find_episode_by_ref).",
    )


class GetEpisodeSegmentsInput(BaseModel):
    episode_id: uuid.UUID | None = Field(
        default=None,
        description="Omit to use session focused_episode_id (auto-pinned by find_episode_by_ref).",
    )
    topic_filter: str | None = None


class SearchWithinEpisodeInput(BaseModel):
    query: str
    episode_id: uuid.UUID | None = Field(
        default=None,
        description="Omit to use session focused_episode_id (auto-pinned by find_episode_by_ref).",
    )
    k: int = 5


class SearchAcrossEpisodesInput(BaseModel):
    query: str
    k: int = 8


class SearchInEpisodesInput(BaseModel):
    query: str
    episode_ids: list[uuid.UUID]
    k: int = 8


class SearchWithTopicPrefilterInput(BaseModel):
    topic: str = Field(
        description=(
            "Topic / theme keyword to pre-filter candidate episodes (e.g. '家常味', '歌單', '開工歌'). "
            "Use this for cross-episode questions where a clear topic spans multiple episodes — "
            "the tool first narrows to episodes matching this topic, then runs hybrid retrieval "
            "ONLY within them, avoiding topic-related-but-wrong-episode chunks from dominating the pool."
        )
    )
    query: str = Field(description="The full retrieval query (typically the user's question itself).")
    k: int = 5


class GetShowOverviewInput(BaseModel):
    pass


class PinEpisodeInput(BaseModel):
    episode_id: uuid.UUID


class UnpinEpisodeInput(BaseModel):
    pass


class ListEpisodesInput(BaseModel):
    n: int = Field(default=5, ge=1, le=20)
    order: Literal["newest", "oldest"] = "newest"
    topic: str | None = None
    year_start: int | None = Field(default=None, ge=2000, le=2100)
    year_end: int | None = Field(default=None, ge=2000, le=2100)

    @model_validator(mode="after")
    def _check_year_range(self) -> "ListEpisodesInput":
        if self.year_start is not None and self.year_end is not None:
            if self.year_start > self.year_end:
                raise ValueError("year_start must be <= year_end")
        return self


# ──────────────────────────────────────────────────────────────────────
# Tool context + registry
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ToolContext:
    """Per-turn DI passed into every tool implementation. The LLM never
    sees this — it's appended to the dispatch call by `_dispatch_tool`."""

    db: AsyncSession
    show_id: uuid.UUID
    state: ChatSessionState
    state_store: ChatSessionStateStore


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    callable: Callable[..., Any]


# ──────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────


_FALLBACK_USER_HINT = (
    "No episode is in focus. Call find_episode_by_ref first to pin an episode, "
    "or supply episode_id explicitly."
)


def _resolve_episode_id(
    arg_episode_id: uuid.UUID | None, ctx: ToolContext
) -> tuple[uuid.UUID | None, dict[str, Any]]:
    """Pre-process episode_id: explicit > session focused > missing-error envelope.

    Returns (effective_id_or_None, envelope_extras_to_merge_into_result).
    When the returned id is None the caller SHALL short-circuit and return the
    extras dict as the tool envelope (it already contains user_hint + error fields).
    """
    if arg_episode_id is not None:
        return arg_episode_id, {"episode_id_source": "explicit"}
    focused = getattr(ctx.state, "focused_episode_id", None)
    if focused is not None:
        return focused, {
            "episode_id_source": "session_focused",
            "effective_episode_id": str(focused),
        }
    return None, {
        "episode_id_source": "missing",
        "user_hint": _FALLBACK_USER_HINT,
        "error": "episode_id required and no session focused_episode_id available",
    }


async def _find_episode_by_ref(inp: FindEpisodeByRefInput, ctx: ToolContext) -> dict:
    ep = await episode_finders.find_by_ref(ctx.db, ctx.show_id, inp.ref)
    if ep is None:
        return {"episode": None, "auto_pinned": False}
    ctx.state.focused_episode_id = ep.episode_id
    ctx.state.focused_episode_at = datetime.now(timezone.utc)
    ctx.state_store.save(ctx.state)
    return {"episode": ep.model_dump(mode="json"), "auto_pinned": True}


async def _find_episodes_by_guest(inp: FindEpisodesByGuestInput, ctx: ToolContext) -> dict:
    eps = await episode_finders.find_episodes_by_guest(ctx.db, ctx.show_id, [inp.name])
    return {"episodes": [e.model_dump(mode="json") for e in eps]}


async def _find_episodes_by_topic(inp: FindEpisodesByTopicInput, ctx: ToolContext) -> dict:
    eps = await episode_finders.find_episodes_by_topic(ctx.db, ctx.show_id, [inp.topic])
    return {"episodes": [e.model_dump(mode="json") for e in eps]}


async def _find_episodes_by_date(inp: FindEpisodesByDateInput, ctx: ToolContext) -> dict:
    start = datetime.combine(inp.start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(inp.end, datetime.max.time(), tzinfo=timezone.utc)
    eps = await episode_finders.find_episodes_by_date_range(
        ctx.db, ctx.show_id, start, end, order=inp.order, limit=inp.limit
    )
    return {"episodes": [e.model_dump(mode="json") for e in eps]}


_EPISODE_SUMMARY_SQL = """
SELECT ai_summary, title
FROM episodes
WHERE id = :episode_id AND show_id = :show_id
"""


async def _get_episode_summary(inp: GetEpisodeSummaryInput, ctx: ToolContext) -> dict:
    effective_id, extras = _resolve_episode_id(inp.episode_id, ctx)
    if effective_id is None:
        return extras
    result = await ctx.db.execute(
        text(_EPISODE_SUMMARY_SQL),
        {"episode_id": effective_id, "show_id": ctx.show_id},
    )
    row = result.mappings().first()
    if row is None:
        return {"summary": None, "error": "episode not found in this show", **extras}
    return {
        "episode_id": str(effective_id),
        "title": row["title"],
        "summary": row["ai_summary"] or "",
        **extras,
    }


_EPISODE_SEGMENTS_SQL = """
SELECT ts.id AS segment_id,
       ts.start_time AS start_sec,
       ts.end_time AS end_sec,
       ts.text,
       ts.topic_label
FROM transcript_segments ts
JOIN transcripts t ON t.id = ts.transcript_id
JOIN episodes e ON e.id = t.episode_id
WHERE e.id = :episode_id AND e.show_id = :show_id
  {topic_clause}
ORDER BY ts.start_time ASC
"""


async def _get_episode_segments(inp: GetEpisodeSegmentsInput, ctx: ToolContext) -> dict:
    effective_id, extras = _resolve_episode_id(inp.episode_id, ctx)
    if effective_id is None:
        return extras
    topic_clause = ""
    params: dict[str, Any] = {"episode_id": effective_id, "show_id": ctx.show_id}
    if inp.topic_filter:
        topic_clause = "AND ts.topic_label ILIKE :topic_filter"
        params["topic_filter"] = f"%{inp.topic_filter}%"
    sql = _EPISODE_SEGMENTS_SQL.format(topic_clause=topic_clause)
    result = await ctx.db.execute(text(sql), params)
    segments = [
        {
            "segment_id": str(r["segment_id"]),
            "start_sec": float(r["start_sec"]) if r["start_sec"] is not None else 0.0,
            "end_sec": float(r["end_sec"]) if r["end_sec"] is not None else 0.0,
            "text": r["text"] or "",
            "topic_label": r["topic_label"],
        }
        for r in result.mappings()
    ]
    return {"episode_id": str(effective_id), "segments": segments, **extras}


async def _embed_query(db: AsyncSession, query: str) -> list[float]:
    step = await get_step_config(db, "embedding")
    return embed_texts([query], step)[0]


def _chunk_to_dict(h: Any) -> dict:
    return {
        "chunk_id": str(h.chunk_id) if getattr(h, "chunk_id", None) else None,
        "episode_id": str(h.episode_id),
        "episode_title": getattr(h, "episode_title", "") or "",
        "start_time": float(getattr(h, "start_time", 0.0) or 0.0),
        "end_time": float(getattr(h, "end_time", 0.0) or 0.0),
        "text": getattr(h, "text", "") or "",
        "rrf_score": float(getattr(h, "rrf_score", 0.0) or 0.0),
        "source": getattr(h, "source", "transcript"),
        "before_text": getattr(h, "before_text", "") or "",
        "after_text": getattr(h, "after_text", "") or "",
        "highlights": getattr(h, "highlights", "") or "",
        "ai_summary_excerpt": getattr(h, "ai_summary_excerpt", "") or "",
        "ai_summary_full": getattr(h, "ai_summary_full", None),
    }


async def _search_within_episode(inp: SearchWithinEpisodeInput, ctx: ToolContext) -> dict:
    effective_id, extras = _resolve_episode_id(inp.episode_id, ctx)
    if effective_id is None:
        return extras
    vec = await _embed_query(ctx.db, inp.query)
    hits = await rag.retrieve_hybrid(
        ctx.db,
        show_id=ctx.show_id,
        query_embedding=vec,
        question=inp.query,
        k=inp.k,
        episode_id_filter=[effective_id],
    )
    return {"chunks": [_chunk_to_dict(h) for h in hits], **extras}


async def _search_across_episodes(inp: SearchAcrossEpisodesInput, ctx: ToolContext) -> dict:
    vec = await _embed_query(ctx.db, inp.query)
    hits = await rag.retrieve_hybrid(
        ctx.db,
        show_id=ctx.show_id,
        query_embedding=vec,
        question=inp.query,
        k=inp.k,
    )
    return {"chunks": [_chunk_to_dict(h) for h in hits]}


async def _search_in_episodes(inp: SearchInEpisodesInput, ctx: ToolContext) -> dict:
    if not inp.episode_ids:
        return {"chunks": []}
    vec = await _embed_query(ctx.db, inp.query)
    hits = await rag.retrieve_hybrid(
        ctx.db,
        show_id=ctx.show_id,
        query_embedding=vec,
        question=inp.query,
        k=inp.k,
        episode_id_filter=list(inp.episode_ids),
    )
    return {"chunks": [_chunk_to_dict(h) for h in hits]}


async def _search_with_topic_prefilter(
    inp: SearchWithTopicPrefilterInput, ctx: ToolContext
) -> dict:
    candidates = await episode_finders.find_episodes_by_topic(
        ctx.db, ctx.show_id, [inp.topic]
    )
    vec = await _embed_query(ctx.db, inp.query)
    if candidates:
        epid_filter = [ep.episode_id for ep in candidates]
        hits = await rag.retrieve_hybrid(
            ctx.db,
            show_id=ctx.show_id,
            query_embedding=vec,
            question=inp.query,
            k=inp.k,
            episode_id_filter=epid_filter,
        )
        return {
            "chunks": [_chunk_to_dict(h) for h in hits],
            "prefilter_episode_count": len(candidates),
            "fallback_to_full_pool": False,
        }
    # No topic match → fall back to full-show retrieval
    hits = await rag.retrieve_hybrid(
        ctx.db,
        show_id=ctx.show_id,
        query_embedding=vec,
        question=inp.query,
        k=inp.k,
    )
    return {
        "chunks": [_chunk_to_dict(h) for h in hits],
        "prefilter_episode_count": 0,
        "fallback_to_full_pool": True,
    }


_SHOW_OVERVIEW_SQL = "SELECT title, description FROM shows WHERE id = :show_id"


async def _get_show_overview(inp: GetShowOverviewInput, ctx: ToolContext) -> dict:
    result = await ctx.db.execute(text(_SHOW_OVERVIEW_SQL), {"show_id": ctx.show_id})
    row = result.mappings().first()
    if row is None:
        return {"overview": None}
    return {"title": row["title"], "overview": row["description"] or ""}


def _pin_episode(inp: PinEpisodeInput, ctx: ToolContext) -> dict:
    already = ctx.state.focused_episode_id == inp.episode_id
    ctx.state.focused_episode_id = inp.episode_id
    ctx.state.focused_episode_at = datetime.now(timezone.utc)
    ctx.state_store.save(ctx.state)
    return {
        "ok": True,
        "focused_episode_id": str(inp.episode_id),
        "already_pinned": already,
    }


def _unpin_episode(inp: UnpinEpisodeInput, ctx: ToolContext) -> dict:
    ctx.state.focused_episode_id = None
    ctx.state.focused_episode_at = None
    ctx.state_store.save(ctx.state)
    return {"ok": True}


async def _list_episodes(inp: ListEpisodesInput, ctx: ToolContext) -> dict:
    out = await episode_finders.find_episodes_by_recency(
        ctx.db,
        ctx.show_id,
        n=inp.n,
        order=inp.order,
        topic=inp.topic,
        year_start=inp.year_start,
        year_end=inp.year_end,
    )
    episodes = out["episodes"]
    return {
        "episodes": [e.model_dump(mode="json") for e in episodes],
        "n_returned": len(episodes),
        "n_total_matched": out["n_total_matched"],
    }


# ──────────────────────────────────────────────────────────────────────
# Registry + dispatcher
# ──────────────────────────────────────────────────────────────────────


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="find_episode_by_ref",
        description=(
            "Resolve a textual episode reference to a single episode. Accepts: "
            "EP numbers ('EP143'), topic refs ('Axios 那集'), relative refs ('上一集'). "
            "DO NOT use for ordinal references like '第 N 集' / '第三集' when a prior "
            "enumeration exists in the system context — those resolve via "
            "`last_enumeration_episodes[N-1]` (use `get_episode_summary` on that ep_id instead)."
        ),
        input_model=FindEpisodeByRefInput,
        callable=_find_episode_by_ref,
    ),
    ToolSpec(
        name="find_episodes_by_guest",
        description="Find episodes whose guests list contains the given name.",
        input_model=FindEpisodesByGuestInput,
        callable=_find_episodes_by_guest,
    ),
    ToolSpec(
        name="find_episodes_by_topic",
        description="Find episodes whose title or description mentions the topic keyword.",
        input_model=FindEpisodesByTopicInput,
        callable=_find_episodes_by_topic,
    ),
    ToolSpec(
        name="find_episodes_by_date",
        description="Find episodes published in the inclusive date range [start, end].",
        input_model=FindEpisodesByDateInput,
        callable=_find_episodes_by_date,
    ),
    ToolSpec(
        name="get_episode_summary",
        description="Get the AI-generated summary for one episode.",
        input_model=GetEpisodeSummaryInput,
        callable=_get_episode_summary,
    ),
    ToolSpec(
        name="get_episode_segments",
        description="List topic-labelled segments for one episode; optional topic_filter narrows by label.",
        input_model=GetEpisodeSegmentsInput,
        callable=_get_episode_segments,
    ),
    ToolSpec(
        name="search_within_episode",
        description="Semantic+keyword search restricted to one episode.",
        input_model=SearchWithinEpisodeInput,
        callable=_search_within_episode,
    ),
    ToolSpec(
        name="search_across_episodes",
        description=(
            "Fallback semantic+keyword search across all episodes in the current show. "
            "For questions spanning a known topic / theme across episodes "
            "(e.g. '主持人怎麼定義家常味', '迪拉跟 Leo 王 怎麼合作'), prefer "
            "search_with_topic_prefilter(topic, query) — that one first narrows to "
            "candidate episodes matching the topic, then retrieves within them, "
            "avoiding topic-related-but-wrong-episode chunks from dominating the merged pool."
        ),
        input_model=SearchAcrossEpisodesInput,
        callable=_search_across_episodes,
    ),
    ToolSpec(
        name="search_in_episodes",
        description="Semantic+keyword search restricted to the given list of episode_ids.",
        input_model=SearchInEpisodesInput,
        callable=_search_in_episodes,
    ),
    ToolSpec(
        name="search_with_topic_prefilter",
        description=(
            "Preferred tool for cross-episode topical questions. Internally first "
            "calls find_episodes_by_topic(topic) to scope to candidate episodes, "
            "then runs hybrid retrieval within them. Falls back to full-show retrieval "
            "if the topic matches no episodes. Returns chunks + prefilter_episode_count "
            "+ fallback_to_full_pool flag."
        ),
        input_model=SearchWithTopicPrefilterInput,
        callable=_search_with_topic_prefilter,
    ),
    ToolSpec(
        name="get_show_overview",
        description="Get a one-paragraph overview of the current show.",
        input_model=GetShowOverviewInput,
        callable=_get_show_overview,
    ),
    ToolSpec(
        name="pin_episode",
        description="Pin one episode_id as focused in L1 session state (10 min idle expiry).",
        input_model=PinEpisodeInput,
        callable=_pin_episode,
    ),
    ToolSpec(
        name="unpin_episode",
        description="Clear the focused_episode_id in L1 session state.",
        input_model=UnpinEpisodeInput,
        callable=_unpin_episode,
    ),
    ToolSpec(
        name="list_episodes",
        description=(
            "列出節目集數，支援依發布時間排序（最新 / 最舊）+ 可選 topic / year_range filter。"
            "適合「最新 N 集 / 最舊 N 集 / 2024 年最後一集歌單」這類 recency-driven query。"
        ),
        input_model=ListEpisodesInput,
        callable=_list_episodes,
    ),
]


TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}


_ENUMERATION_TOOL_NAMES = {
    "find_episodes_by_guest",
    "find_episodes_by_topic",
    "find_episodes_by_date",
    "list_episodes",
}


def _pydantic_to_openai_function(spec: ToolSpec) -> dict:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.input_model.model_json_schema(),
        },
    }


OPENAI_TOOLS_SPEC: list[dict] = [_pydantic_to_openai_function(t) for t in TOOLS]


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map an exception to (kind, user_hint) per the chat-tool-error-isolation
    design (Decision 3 dispatch table).

    `kind` is one of: validation / schema / transient / not_found / unknown.
    `user_hint` is a zh-TW phrasing safe to surface to end-users — it MUST
    NOT contain exception class names, column names, or phrases that imply
    internal system failure ("技術問題" / "系統查詢" / etc).
    """
    if isinstance(exc, ValidationError):
        return ("validation", "查詢條件有點不太對，請再試一次")
    if isinstance(exc, (ProgrammingError, IntegrityError, DataError)):
        return ("schema", "這次查詢沒撈到完整資料")
    if isinstance(exc, OperationalError):
        return ("transient", "這次查詢遇到一點狀況，可以再問一次")
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ("transient", "這次查詢遇到一點狀況，可以再問一次")
    if isinstance(exc, LookupError):
        return ("not_found", "找不到對應的資料")
    return ("unknown", "這次查詢遇到一點狀況")


def _make_envelope(exc: BaseException) -> dict:
    """Build a Tool error envelope dict from a caught exception."""
    kind, user_hint = _classify_exception(exc)
    return {
        "ok": False,
        "kind": kind,
        "internal_message": f"{type(exc).__name__}: {exc}",
        "user_hint": user_hint,
    }


async def _dispatch_tool(
    name: str,
    args: dict[str, Any],
    ctx: ToolContext,
) -> tuple[dict, str | None, float]:
    """Validate `args`, run the tool inside a SAVEPOINT, catch exceptions.

    Returns `(result_dict, raised_class_name_or_None, latency_ms)`. On
    success `result_dict` is whatever the tool callable produced. On
    failure `result_dict` is a structured Tool error envelope
    `{"ok": false, "kind": "...", "internal_message": "...", "user_hint": "..."}`
    so the LLM has a `kind` for decision-making and a `user_hint` for the
    user-facing reply, while `internal_message` is preserved for trace /
    log analysis.

    SAVEPOINT isolation: the tool callable runs inside a SQLAlchemy
    `begin_nested()` context manager so any DB exception triggers a
    SAVEPOINT rollback before propagating. Subsequent tool calls on the
    same `AsyncSession` then start from a clean transaction state instead
    of inheriting `InFailedSQLTransactionError`.

    Side effect: when an enumeration tool succeeds, its episode IDs are
    written back to `ctx.state.last_enumeration_episodes` (FIFO-capped at
    20) and the state is persisted with a refreshed TTL. This is what
    fixes the bake-off multi-turn carry regression.
    """

    start = time.perf_counter()
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        elapsed = (time.perf_counter() - start) * 1000.0
        return (
            {
                "ok": False,
                "kind": "validation",
                "internal_message": f"UnknownTool: {name}",
                "user_hint": "查詢條件有點不太對，請再試一次",
            },
            "UnknownTool",
            elapsed,
        )

    try:
        validated = spec.input_model.model_validate(args)
    except ValidationError as exc:
        elapsed = (time.perf_counter() - start) * 1000.0
        return _make_envelope(exc), "ValidationError", elapsed

    # SAVEPOINT-wrapped tool execution. Any exception inside the `with`
    # block triggers savepoint rollback before propagating out, so the
    # outer AsyncSession transaction is not poisoned for subsequent tool
    # calls in the same agent loop. If `begin_nested()` itself raises
    # (outer transaction already broken), the classifier falls back to
    # `kind="transient"` (OperationalError) or `kind="unknown"` so the
    # agent loop continues.
    try:
        async with ctx.db.begin_nested():
            result = spec.callable(validated, ctx)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                result = {"value": result}
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000.0
        logger.exception("chat_agent tool %s raised", name)
        return _make_envelope(exc), type(exc).__name__, elapsed

    if name in _ENUMERATION_TOOL_NAMES:
        _writeback_enumeration_anchor(result, ctx)

    elapsed = (time.perf_counter() - start) * 1000.0
    return result, None, elapsed


def _writeback_enumeration_anchor(result: dict, ctx: ToolContext) -> None:
    """Append episode IDs from a successful enumeration result onto the
    L1 anchor and persist (FIFO cap is enforced inside the model
    validator). Errors here are swallowed: write-back is best-effort,
    the user-facing answer takes priority."""

    episodes = result.get("episodes") if isinstance(result, dict) else None
    if not episodes:
        return
    new_ids: list[uuid.UUID] = []
    for e in episodes:
        try:
            new_ids.append(uuid.UUID(e["episode_id"]))
        except (KeyError, ValueError, TypeError):
            continue
    if not new_ids:
        return
    combined = list(ctx.state.last_enumeration_episodes) + new_ids
    # Reuse the model's FIFO validator by going through model_validate
    refreshed = ChatSessionState.model_validate(
        {**ctx.state.model_dump(), "last_enumeration_episodes": combined}
    )
    ctx.state.last_enumeration_episodes = refreshed.last_enumeration_episodes
    ctx.state.last_enumeration_at = datetime.now(timezone.utc)
    try:
        ctx.state_store.save(ctx.state)
    except Exception:
        logger.exception("chat_agent: enumeration write-back save failed (continuing)")
