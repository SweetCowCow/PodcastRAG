"""RAG retrieval orchestration.

Hybrid retrieval (semantic pgvector + lexical PG tsvector via RRF), two-layer
episode routing, and the per-pool merge in ``retrieve_hybrid``. Composes the
SQL builders/templates from ``rag_sql`` and the tuning knobs from
``rag_config``.
"""
from __future__ import annotations

import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import tokenizer
from app.services.rag_types import ChunkHit, MetadataFilters
from app.services.rag_config import (
    DESCRIPTION_CAP,
    RETRIEVAL_TOP_K,
    ROUTE_EPISODES_K,
    RRF_K,
    RRF_PER_SIDE,
    RRF_WEIGHTS,
    TITLE_RRF_PER_SIDE,
    _DESCRIPTION_CAP_RUNTIME,
    _resolve_embed_placeholders,
)
from app.services.rag_sql import (
    _DESC_RRF_SQL,
    _DESC_SEMANTIC_ONLY_SQL,
    _ROUTE_EPISODES_SQL,
    _TITLE_LEXICAL_SQL,
    _TRANSCRIPT_RRF_SQL,
    _TRANSCRIPT_SEMANTIC_ONLY_SQL,
    _build_ts_query,
    _episode_filter_clause,
    _metadata_filter_clause,
    _validate_query_dim,
    _vector_literal,
)

__all__ = [
    "retrieve",
    "retrieve_descriptions",
    "retrieve_titles",
    "route_episodes",
    "retrieve_hybrid",
    "_should_skip_routing",
]


async def retrieve(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    question: str = "",
    k: int = RETRIEVAL_TOP_K,
    episode_id_filter: list[uuid.UUID] | None = None,
    metadata_filters: MetadataFilters | None = None,
) -> list[ChunkHit]:
    """Hybrid (RRF) retrieval over `transcript_chunks` for one show.

    If the question yields no usable lexical query, falls back to
    semantic-only ranking. Optional `episode_id_filter` restricts both
    semantic and lexical CTEs to the given episode set (used by the
    R3.2 two-layer routing flow). Optional `metadata_filters` adds
    `episodes.guests` / `episodes.published_at` hard-filter clauses
    (R3.3 Phase 8).
    """
    _validate_query_dim(query_embedding)
    ts_query = _build_ts_query(question) if question else None

    base_params: dict = {
        "query_embedding": _vector_literal(query_embedding),
        "show_id": show_id,
        "k": k,
    }
    ep_filter = _episode_filter_clause("e", base_params, episode_id_filter)
    md_filter = _metadata_filter_clause("e", base_params, metadata_filters)

    if ts_query:
        sql = text(
            _resolve_embed_placeholders(_TRANSCRIPT_RRF_SQL).format(
                episode_filter=ep_filter,
                metadata_filter=md_filter,
            )
        )
        base_params["ts_query"] = ts_query
        base_params["per_side"] = RRF_PER_SIDE
        base_params["rrf_k"] = RRF_K
        base_params["weight_chunk"] = RRF_WEIGHTS["chunk"]
        result = await db.execute(sql, base_params)
        return [
            ChunkHit(
                chunk_id=row["chunk_id"],
                episode_id=row["episode_id"],
                episode_title=row["episode_title"],
                start_time=float(row["start_time"]),
                end_time=float(row["end_time"]),
                text=row["text"],
                rrf_score=float(row["rrf_score"]),
                source="transcript",
            )
            for row in result.mappings()
        ]

    # No lexical signal — fall back to pure semantic.
    sql = text(
        _resolve_embed_placeholders(_TRANSCRIPT_SEMANTIC_ONLY_SQL).format(
            episode_filter=ep_filter,
            metadata_filter=md_filter,
        )
    )
    result = await db.execute(sql, base_params)
    return [
        ChunkHit(
            chunk_id=row["chunk_id"],
            episode_id=row["episode_id"],
            episode_title=row["episode_title"],
            start_time=float(row["start_time"]),
            end_time=float(row["end_time"]),
            text=row["text"],
            distance=float(row["distance"]),
            source="transcript",
        )
        for row in result.mappings()
    ]


async def retrieve_descriptions(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    question: str = "",
    k: int = RETRIEVAL_TOP_K,
    episode_id_filter: list[uuid.UUID] | None = None,
    metadata_filters: MetadataFilters | None = None,
) -> list[ChunkHit]:
    """Hybrid (RRF) retrieval over `episode_description_chunks` for one show.

    Description hits carry `source='description'` and zero start/end times
    so client-side "play from this time" UI can skip the affordance.
    """
    _validate_query_dim(query_embedding)
    ts_query = _build_ts_query(question) if question else None

    base_params: dict = {
        "query_embedding": _vector_literal(query_embedding),
        "show_id": show_id,
        "k": k,
    }
    ep_filter = _episode_filter_clause("e", base_params, episode_id_filter)
    md_filter = _metadata_filter_clause("e", base_params, metadata_filters)

    if ts_query:
        sql = text(
            _resolve_embed_placeholders(_DESC_RRF_SQL).format(
                episode_filter=ep_filter,
                metadata_filter=md_filter,
            )
        )
        base_params["ts_query"] = ts_query
        base_params["per_side"] = RRF_PER_SIDE
        base_params["rrf_k"] = RRF_K
        base_params["weight_desc"] = RRF_WEIGHTS["description"]
        result = await db.execute(sql, base_params)
        return [
            ChunkHit(
                chunk_id=row["chunk_id"],
                episode_id=row["episode_id"],
                episode_title=row["episode_title"],
                start_time=0.0,
                end_time=0.0,
                text=row["text"],
                rrf_score=float(row["rrf_score"]),
                source="description",
                chunking_version=int(row["chunking_version"]),
                chunk_index=int(row["chunk_index"]),
            )
            for row in result.mappings()
        ]

    sql = text(
        _resolve_embed_placeholders(_DESC_SEMANTIC_ONLY_SQL).format(
            episode_filter=ep_filter,
            metadata_filter=md_filter,
        )
    )
    result = await db.execute(sql, base_params)
    return [
        ChunkHit(
            chunk_id=row["chunk_id"],
            episode_id=row["episode_id"],
            episode_title=row["episode_title"],
            start_time=0.0,
            end_time=0.0,
            text=row["text"],
            distance=float(row["distance"]),
            source="description",
            chunking_version=int(row["chunking_version"]),
            chunk_index=int(row["chunk_index"]),
        )
        for row in result.mappings()
    ]


async def retrieve_titles(
    db: AsyncSession,
    show_id: uuid.UUID,
    question: str,
    k: int = RETRIEVAL_TOP_K,
    episode_id_filter: list[uuid.UUID] | None = None,
    metadata_filters: MetadataFilters | None = None,
) -> list[ChunkHit]:
    """Lexical-only retrieval over `episodes.title_tsvector` (R3.3 Phase 8.3).

    Returns at most `k` hits with `source='title'`, `text=<episode title>`,
    and `chunk_id=None` (title pool is episode-keyed, not chunk-keyed).
    Yields empty list when the question produces no usable lexical query
    or when no episode title matches.
    """
    ts_query = _build_ts_query(question) if question else None
    if not ts_query:
        return []

    base_params: dict = {
        "show_id": show_id,
        "k": k,
        "ts_query": ts_query,
        "per_side": TITLE_RRF_PER_SIDE,
        "rrf_k": RRF_K,
        "weight_title": RRF_WEIGHTS["title"],
    }
    ep_filter = _episode_filter_clause("e", base_params, episode_id_filter)
    md_filter = _metadata_filter_clause("e", base_params, metadata_filters)

    sql = text(
        _TITLE_LEXICAL_SQL.format(
            episode_filter=ep_filter,
            metadata_filter=md_filter,
        )
    )
    result = await db.execute(sql, base_params)
    return [
        ChunkHit(
            chunk_id=None,
            episode_id=row["episode_id"],
            episode_title=row["episode_title"],
            start_time=0.0,
            end_time=0.0,
            text=row["episode_title"],
            rrf_score=float(row["rrf_score"]),
            source="title",
        )
        for row in result.mappings()
    ]


def _should_skip_routing(question: str) -> bool:
    """True when the question is too short to route reliably, OR when the
    operator has disabled two-layer routing via env flag.

    Env flag: `ENABLE_TWO_LAYER_ROUTING` (default "false"; set to "true" to
    re-enable routing for diagnostics). The 2026-05-13 audit showed routing
    was a net negative on human-curated queries (Recall@5 0.0625 with routing
    vs 0.4375 without). See r3-5-disable-routing change for the spike data
    and `docs/case-studies/r32-routing-regression-2026-05-11.md` for the
    original 2026-05-11 hotfix context (now superseded).

    Routing relies on description embedding similarity. Questions with
    fewer than 2 multi-char (length>=2) jieba tokens (e.g. just '迪拉胖')
    yield poor embedding signal — when routing IS re-enabled, we'd rather
    search the whole show.
    """
    if os.getenv("ENABLE_TWO_LAYER_ROUTING", "false").strip().lower() == "false":
        return True
    if not question or not question.strip():
        return True
    tokens = tokenizer.tokenize(question)
    multi_char = [t for t in tokens if len(t) >= 2]
    return len(multi_char) < 2


async def route_episodes(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    k: int = ROUTE_EPISODES_K,
) -> list[uuid.UUID]:
    """First-layer routing: top-k episode_id by description embedding cosine."""
    _validate_query_dim(query_embedding)
    sql = text(_resolve_embed_placeholders(_ROUTE_EPISODES_SQL))
    result = await db.execute(
        sql,
        {
            "query_embedding": _vector_literal(query_embedding),
            "show_id": show_id,
            "k": k,
        },
    )
    return [row["episode_id"] for row in result.mappings()]


async def retrieve_hybrid(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    question: str = "",
    k: int = RETRIEVAL_TOP_K,
    episode_id_filter: list[uuid.UUID] | None = None,
    metadata_filters: MetadataFilters | None = None,
) -> list[ChunkHit]:
    """Run transcript + description + title retrieval and merge by RRF score.

    Applies DESCRIPTION_CAP: at most `DESCRIPTION_CAP` description hits in
    the returned top-K. Excess description hits are replaced (in rank
    order) by the next-best transcript hits if any are available. Title
    hits (R3.3 Phase 8) join the merge weighted by `RRF_WEIGHTS["title"]`
    and are not subject to DESCRIPTION_CAP.
    """
    transcript_hits = await retrieve(
        db, show_id, query_embedding, question, k=k,
        episode_id_filter=episode_id_filter,
        metadata_filters=metadata_filters,
    )
    desc_hits = await retrieve_descriptions(
        db, show_id, query_embedding, question, k=k,
        episode_id_filter=episode_id_filter,
        metadata_filters=metadata_filters,
    )
    title_hits = await retrieve_titles(
        db, show_id, question, k=k,
        episode_id_filter=episode_id_filter,
        metadata_filters=metadata_filters,
    )

    # Merge by RRF score (existing behaviour). Title hits have chunk_id=None
    # so they bypass the chunk_id dedupe set.
    seen: set[uuid.UUID] = set()
    ranked: list[ChunkHit] = []
    for h in sorted(
        transcript_hits + desc_hits + title_hits,
        key=lambda x: (x.rrf_score, -(x.distance or 0.0)),
        reverse=True,
    ):
        if h.chunk_id and h.chunk_id in seen:
            continue
        if h.chunk_id:
            seen.add(h.chunk_id)
        ranked.append(h)

    # Apply DESCRIPTION_CAP: at most N description hits, prefer transcript
    # to fill the rest. If transcripts run out, fall back to filling with
    # extra description hits (cap waived).
    final: list[ChunkHit] = []
    desc_count = 0
    extras: list[ChunkHit] = []
    for h in ranked:
        if len(final) >= k:
            break
        if h.source == "description":
            if desc_count < _DESCRIPTION_CAP_RUNTIME:
                final.append(h)
                desc_count += 1
            else:
                extras.append(h)
        else:
            final.append(h)
    # If we have spare slots and only extras left, use them (cap waiver).
    while len(final) < k and extras:
        final.append(extras.pop(0))
    return final


# ---------------------------------------------------------------------------
# R2.1 citation infra: source enrichment helpers
# ---------------------------------------------------------------------------
#
# `enrich_hits()` augments a list of `ChunkHit` returned from retrieval with
# four extra fields that the frontend SourceCard renders:
#
#   - before_text: concatenated text of up to 2 preceding `transcript_segments`
#   - after_text:  concatenated text of up to 2 following `transcript_segments`
#   - highlights:  `ts_headline()` output wrapping query-token matches in
#                  `<mark>...</mark>` tags (no other HTML)
#   - ai_summary_excerpt: first 60 chars of the episode's `ai_summary`, with a
#                  trailing `…` if truncated
#
# Description-source hits get empty before/after_text (descriptions have no
# segment-level neighbours per the spec), but their `highlights` are still
# computed against the description text.
#
# We compute jieba tokens *once* per call (using `tokenizer.tokenize`) and feed
# the same `to_tsquery('simple', ...)` string used by RRF retrieval so that
# highlight tokens line up with what was actually retrieved.
