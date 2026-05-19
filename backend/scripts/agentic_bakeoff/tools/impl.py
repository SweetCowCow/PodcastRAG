"""11 callable implementations for the 9 bake-off tools.

Per design.md「9 Tool Spec」table:
- #1, #5, #6, #7a, #7c, #8  → stub fixtures
- #2, #3, #4                 → wrap existing episode_finders (real DB)
- #7b                        → wrap rag.retrieve_hybrid (real DB + embedding)
- #9 pin / unpin             → write Redis L1 state
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.services import episode_finders, rag
from app.services.ai_step_resolver import get_step_config
from app.services.embedding import embed_texts

from ..state import load_state, save_state
from . import fixtures, schemas
from .context import ToolContext


# ---- 1. find_episode_by_ref (stub) ----

def find_episode_by_ref(
    inp: schemas.FindEpisodeByRefInput, ctx: ToolContext
) -> schemas.FindEpisodeByRefOutput:
    ep_id = fixtures.REF_LOOKUP.get(inp.ref.strip())
    if ep_id is None:
        return schemas.FindEpisodeByRefOutput(episode=None)
    return schemas.FindEpisodeByRefOutput(
        episode=fixtures.FIXTURE_EPISODES[ep_id]
    )


# ---- 2. find_episodes_by_guest (real) ----

async def find_episodes_by_guest(
    inp: schemas.FindEpisodesByGuestInput, ctx: ToolContext
) -> schemas.EpisodeListOutput:
    async with ctx.db_factory() as db:
        rows = await episode_finders.find_episodes_by_guest(
            db, ctx.show_id, [inp.name]
        )
    return schemas.EpisodeListOutput(
        episodes=[schemas.EpisodeRef.model_validate(r.model_dump()) for r in rows]
    )


# ---- 3. find_episodes_by_topic (real) ----

async def find_episodes_by_topic(
    inp: schemas.FindEpisodesByTopicInput, ctx: ToolContext
) -> schemas.EpisodeListOutput:
    async with ctx.db_factory() as db:
        rows = await episode_finders.find_episodes_by_topic(
            db, ctx.show_id, [inp.topic]
        )
    return schemas.EpisodeListOutput(
        episodes=[schemas.EpisodeRef.model_validate(r.model_dump()) for r in rows]
    )


# ---- 4. find_episodes_by_date (real) ----

async def find_episodes_by_date(
    inp: schemas.FindEpisodesByDateInput, ctx: ToolContext
) -> schemas.EpisodeListOutput:
    start_dt = datetime.combine(inp.start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(inp.end, datetime.max.time(), tzinfo=timezone.utc)
    async with ctx.db_factory() as db:
        rows = await episode_finders.find_episodes_by_date_range(
            db, ctx.show_id, start_dt, end_dt
        )
    return schemas.EpisodeListOutput(
        episodes=[schemas.EpisodeRef.model_validate(r.model_dump()) for r in rows]
    )


# ---- 5. get_episode_summary (stub) ----

def get_episode_summary(
    inp: schemas.GetEpisodeSummaryInput, ctx: ToolContext
) -> schemas.GetEpisodeSummaryOutput:
    return schemas.GetEpisodeSummaryOutput(
        summary=fixtures.fixture_summary(inp.episode_id)
    )


# ---- 6. get_episode_segments (stub) ----

def get_episode_segments(
    inp: schemas.GetEpisodeSegmentsInput, ctx: ToolContext
) -> schemas.SegmentListOutput:
    return schemas.SegmentListOutput(
        segments=fixtures.fixture_segments(inp.episode_id, inp.topic_filter)
    )


# ---- 7a. search_within_episode (stub) ----

def search_within_episode(
    inp: schemas.SearchWithinEpisodeInput, ctx: ToolContext
) -> schemas.ChunkListOutput:
    return schemas.ChunkListOutput(
        chunks=fixtures.fixture_chunks(inp.query, inp.episode_id, inp.k)
    )


# ---- 7b. search_across_episodes (REAL — wraps retrieve_hybrid) ----

async def search_across_episodes(
    inp: schemas.SearchAcrossEpisodesInput, ctx: ToolContext
) -> schemas.ChunkListOutput:
    async with ctx.db_factory() as db:
        step = await get_step_config(db, "embedding")
        vec = embed_texts([inp.query], step)[0]
        hits = await rag.retrieve_hybrid(
            db,
            show_id=ctx.show_id,
            query_embedding=vec,
            question=inp.query,
            k=inp.k,
        )
    return schemas.ChunkListOutput(
        chunks=[
            schemas.ChunkHit(
                chunk_id=h.chunk_id,
                episode_id=h.episode_id,
                episode_title=getattr(h, "episode_title", "") or "",
                text=getattr(h, "text", "") or "",
                rrf_score=float(h.rrf_score or 0.0),
                pool=getattr(h, "source_pool", "transcript"),
            )
            for h in hits
        ]
    )


# ---- 7c. search_in_episodes (stub) ----

def search_in_episodes(
    inp: schemas.SearchInEpisodesInput, ctx: ToolContext
) -> schemas.ChunkListOutput:
    out: list[schemas.ChunkHit] = []
    for ep_id in inp.episode_ids:
        out.extend(fixtures.fixture_chunks(inp.query, ep_id, max(1, inp.k // max(1, len(inp.episode_ids)))))
    return schemas.ChunkListOutput(chunks=out[: inp.k])


# ---- 8. get_show_overview (stub) ----

def get_show_overview(
    inp: schemas.GetShowOverviewInput, ctx: ToolContext
) -> schemas.GetShowOverviewOutput:
    return schemas.GetShowOverviewOutput(overview=fixtures.fixture_overview())


# ---- 9. pin_episode / unpin_episode (REAL — write Redis L1 state) ----

def pin_episode(
    inp: schemas.PinEpisodeInput, ctx: ToolContext
) -> schemas.OkOutput:
    state = load_state(ctx.redis_client, ctx.session_id, ctx.show_id)
    state.focused_episode_id = inp.episode_id
    state.focused_episode_pinned_at = datetime.now(timezone.utc)
    save_state(ctx.redis_client, state)
    return schemas.OkOutput(ok=True)


def unpin_episode(
    inp: schemas.UnpinEpisodeInput, ctx: ToolContext
) -> schemas.OkOutput:
    state = load_state(ctx.redis_client, ctx.session_id, ctx.show_id)
    state.focused_episode_id = None
    state.focused_episode_pinned_at = None
    save_state(ctx.redis_client, state)
    return schemas.OkOutput(ok=True)
