"""RAG retrieval + answer pipeline — compatibility facade.

The implementation was split into single-responsibility modules
(``rag_types`` / ``rag_config`` / ``rag_sql`` / ``rag_retrieval`` /
``rag_enrich`` / ``rag_generation``). This module re-exports their public
symbols so existing ``rag.<symbol>`` access and ``from app.services.rag import
<symbol>`` imports keep working unchanged.

Do NOT add business logic here — put new code in the module matching its
concern and re-export it below if it needs to be reachable via the facade.
"""
from __future__ import annotations

from app.services.rag_config import (
    DESCRIPTION_CAP,
    HISTORY_WINDOW,
    RETRIEVAL_TOP_K,
    ROUTE_EPISODES_K,
    RRF_K,
    RRF_PER_SIDE,
    RRF_WEIGHTS,
    TITLE_RRF_PER_SIDE,
    _DESCRIPTION_CAP_RUNTIME,
    _EMB_LHS_C,
    _EMB_LHS_D,
    _EMB_NN_C,
    _EMB_NN_D,
    _EMB_RHS,
    _EXPECTED_QUERY_DIM,
    _SHOW_NAME_FILTER_ENABLED,
    _USE_EMBEDDING_V2,
    _parse_runtime_description_cap,
    _parse_runtime_show_name_filter,
    _parse_use_embedding_v2,
    _resolve_embed_placeholders,
)
from app.services.rag_enrich import (
    enrich_hits,
    _strip_non_mark_tags,
    _truncate_ai_summary,
)
from app.services.rag_generation import (
    ENUMERATION_BLOCK_MAX_LIST_ROWS,
    REWRITE_SYSTEM_PROMPT,
    answer_with_chunks,
    format_enumeration_block,
    rewrite_question,
    strip_citations,
    _chat_with_tracker,
    _extract_answer_from_malformed_json,
    _hit_key,
    _unwrap_self_referential_json,
)
from app.services.rag_retrieval import (
    retrieve,
    retrieve_descriptions,
    retrieve_hybrid,
    retrieve_titles,
    route_episodes,
    _should_skip_routing,
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
from app.services.rag_types import ChunkHit, MetadataFilters

__all__ = [
    # types
    "ChunkHit",
    "MetadataFilters",
    # config constants
    "RETRIEVAL_TOP_K",
    "RRF_K",
    "RRF_PER_SIDE",
    "DESCRIPTION_CAP",
    "ROUTE_EPISODES_K",
    "HISTORY_WINDOW",
    "RRF_WEIGHTS",
    "TITLE_RRF_PER_SIDE",
    # retrieval
    "retrieve",
    "retrieve_descriptions",
    "retrieve_titles",
    "route_episodes",
    "retrieve_hybrid",
    # enrichment
    "enrich_hits",
    # generation
    "REWRITE_SYSTEM_PROMPT",
    "ENUMERATION_BLOCK_MAX_LIST_ROWS",
    "rewrite_question",
    "format_enumeration_block",
    "answer_with_chunks",
    "strip_citations",
]
