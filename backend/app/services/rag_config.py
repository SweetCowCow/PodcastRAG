"""RAG runtime configuration: env-flag parsing, tuning constants, and the
embedding-column selection block.

Sits just above ``rag_types`` in the dependency order. All env reads happen at
import time (the r3-2 lever-test pattern), so unit tests re-parse by calling
``importlib.reload`` on THIS module. ``RRF_WEIGHTS`` is defined here once and
shared by reference — retrieval reads it and the admin RRF sweep mutates it
in place; never rebind the name.
"""
from __future__ import annotations

import os

__all__ = [
    "RETRIEVAL_TOP_K",
    "RRF_K",
    "RRF_PER_SIDE",
    "DESCRIPTION_CAP",
    "ROUTE_EPISODES_K",
    "HISTORY_WINDOW",
    "RRF_WEIGHTS",
    "TITLE_RRF_PER_SIDE",
    "_parse_runtime_description_cap",
    "_parse_runtime_show_name_filter",
    "_DESCRIPTION_CAP_RUNTIME",
    "_SHOW_NAME_FILTER_ENABLED",
    "_parse_use_embedding_v2",
    "_USE_EMBEDDING_V2",
    "_EMB_LHS_C",
    "_EMB_LHS_D",
    "_EMB_RHS",
    "_EMB_NN_C",
    "_EMB_NN_D",
    "_EXPECTED_QUERY_DIM",
    "_resolve_embed_placeholders",
]

RETRIEVAL_TOP_K = 8
RRF_K = 60
RRF_PER_SIDE = 50
DESCRIPTION_CAP = 3
ROUTE_EPISODES_K = 10
HISTORY_WINDOW = 10

# R3.3 Phase 8: per-pool RRF weights for the three-pool lexical fusion. The
# semantic pool always contributes with weight 1.0 (not listed here). Editing
# these values + redeploying is the only step required to tune lexical signal
# strength — no tsvector rebuild or DB migration.
RRF_WEIGHTS: dict[str, float] = {
    "chunk": 1.0,
    "description": 0.7,
    "title": 0.5,
}
# Title pool corpus is at most 1 row per episode (~hundreds), so it ranks
# fast. A small per-side cap keeps the union bounded.
TITLE_RRF_PER_SIDE = 20


def _parse_runtime_description_cap() -> int:
    """Read RAG_DESCRIPTION_CAP at import time. Fall back to DESCRIPTION_CAP
    on missing / malformed / negative value, with a single stderr warning.

    Introduced by r3-2-retrieval-fix as a lever-test knob (2026-05-11)."""
    raw = os.getenv("RAG_DESCRIPTION_CAP")
    if raw is None or raw == "":
        return DESCRIPTION_CAP
    try:
        val = int(raw)
        if val < 0:
            raise ValueError("must be >= 0")
        return val
    except (ValueError, TypeError):
        import sys as _sys
        print(
            f"[warn] RAG_DESCRIPTION_CAP={raw!r} is not a non-negative int; "
            f"falling back to in-code DESCRIPTION_CAP={DESCRIPTION_CAP}",
            file=_sys.stderr,
        )
        return DESCRIPTION_CAP


def _parse_runtime_show_name_filter() -> bool:
    """Read RAG_SHOW_NAME_FILTER at import time. Returns False only when set
    to a recognized disable token; otherwise True (preserves current strip
    behaviour for unset / any other value)."""
    raw = os.getenv("RAG_SHOW_NAME_FILTER", "").strip().lower()
    if raw in ("false", "0", "off"):
        return False
    return True


_DESCRIPTION_CAP_RUNTIME: int = _parse_runtime_description_cap()
_SHOW_NAME_FILTER_ENABLED: bool = _parse_runtime_show_name_filter()


# r3-4: read-side env flag. When true, retrieval uses `embedding_v2`
# (vector(3072), text-embedding-3-large) instead of `embedding` (vector(1536),
# text-embedding-3-small). Read once at import (R3.2 lever-test pattern).
def _parse_use_embedding_v2() -> bool:
    raw = os.getenv("RAG_USE_EMBEDDING_V2", "").strip().lower()
    return raw in ("true", "1", "on")


_USE_EMBEDDING_V2: bool = _parse_use_embedding_v2()


# Column name + distance expression. The v2 path casts to halfvec(3072) so
# the HNSW index built over `(embedding_v2::halfvec(3072)) halfvec_cosine_ops`
# is hit. The query embedding is cast to halfvec to match. Without the cast,
# Postgres would evaluate against the raw vector(3072) column which has no
# usable ANN index (vector_cosine_ops HNSW maxDim is 2000).
if _USE_EMBEDDING_V2:
    _EMB_LHS_C = "c.embedding_v2::halfvec(3072)"
    _EMB_LHS_D = "d.embedding_v2::halfvec(3072)"
    _EMB_RHS = "CAST(:query_embedding AS halfvec(3072))"
    _EMB_NN_C = "c.embedding_v2 IS NOT NULL"
    _EMB_NN_D = "d.embedding_v2 IS NOT NULL"
    _EXPECTED_QUERY_DIM = 3072
else:
    _EMB_LHS_C = "c.embedding"
    _EMB_LHS_D = "d.embedding"
    _EMB_RHS = "CAST(:query_embedding AS vector)"
    _EMB_NN_C = "c.embedding IS NOT NULL"
    _EMB_NN_D = "d.embedding IS NOT NULL"
    _EXPECTED_QUERY_DIM = 1536


def _resolve_embed_placeholders(sql: str) -> str:
    """Replace `__EMB_*__` placeholders in a SQL template per `_USE_EMBEDDING_V2`.

    Done at function-call time (not module import) so unit tests can monkey
    patch `_USE_EMBEDDING_V2` and `_EMB_*` constants and the next retrieval
    call picks up the change. Production startup pays this cost once per
    retrieval call which is negligible.
    """
    return (
        sql.replace("__EMB_LHS_C__", _EMB_LHS_C)
        .replace("__EMB_LHS_D__", _EMB_LHS_D)
        .replace("__EMB_RHS__", _EMB_RHS)
        .replace("__EMB_NN_C__", _EMB_NN_C)
        .replace("__EMB_NN_D__", _EMB_NN_D)
    )
