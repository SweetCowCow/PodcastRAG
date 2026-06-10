"""Service-layer RAG result cache (change: r4-rag-result-cache).

A single Redis-backed cache shared by all three query surfaces:

- semantic ``/search`` and the chat agent's internal retrieval tools both go
  through ``embed_texts`` + ``rag.retrieve_hybrid`` — caching at *those*
  functions (the service layer, not the endpoint) means every mode that calls
  them benefits, including the agent's per-tool searches. Only the chat
  agent's final LLM-generated answer is intentionally NOT cached.
- keyword ``/keyword-search`` caches its three-stage SQL result.

Design highlights (see the change's design.md):

- **Versioned invalidation, not deletion.** Retrieval / keyword keys embed a
  per-show ``corpus_version`` (Redis counter, bumped on transcription complete
  and ASR-correction apply) and a request-time ``retrieval_config_version``
  (hash of the runtime-tunable retrieval knobs). When the corpus or config
  changes, old keys simply stop being looked up. A fallback TTL bounds growth.
- **Fail-open.** Every Redis / (de)serialization error is caught, logged, and
  degraded to a cache miss (getters) or a no-op (setters). A cache failure can
  never fail a query. ``settings.rag_cache_enabled`` is a master kill-switch.
- **Schema-versioned values.** ``CACHE_SCHEMA_VERSION`` is part of every key,
  so a change to the serialized value shape invalidates old entries instead of
  risking a malformed deserialize.

The P2 semantic cache (``semantic_lookup`` / ``semantic_store``) is machinery
gated behind ``settings.enable_semantic_cache`` (default off). This change does
NOT flip it on; the enable gate (false-hit rate ≤5% with net hit-rate gain) is
documented in the design and depends on the EQ5 golden set.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import math
import os
import unicodedata
import uuid
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

import redis

from app.core.config import settings
from app.services import rag_config
from app.services.rag_types import ChunkHit

logger = logging.getLogger(__name__)

# Tracks whether the most recent retrieve_hybrid call in the current async
# context was served from cache, so the chat agent's tools can surface a
# per-tool cache_hit in their (admin-only) debug trace without changing
# retrieve_hybrid's return type.
_last_retrieval_hit: ContextVar[bool] = ContextVar(
    "rag_cache_last_retrieval_hit", default=False
)


def note_retrieval_cache_hit(hit: bool) -> None:
    _last_retrieval_hit.set(hit)


def last_retrieval_cache_hit() -> bool:
    return _last_retrieval_hit.get()


# Bump when the serialized shape of any cached value changes incompatibly.
CACHE_SCHEMA_VERSION = 1

_CORPUS_VER_KEY = "rag:corpus_ver:{show_id}"
_SEM_LIST_KEY = "rag:sem:{show_id}"
# Cap the brute-force semantic-cache candidate list per show (P2 machinery).
_SEM_LIST_CAP = 200
# Queries shorter than this (after normalization) are too underspecified to
# safely serve from the semantic cache — they are excluded from lookup/store.
SEMANTIC_MIN_QUERY_CHARS = 6

_HIT_FIELDS = {f.name for f in dataclasses.fields(ChunkHit)}
_HIT_UUID_FIELDS = {"episode_id", "chunk_id"}


@lru_cache(maxsize=1)
def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.celery_broker_url)


def _enabled() -> bool:
    return settings.rag_cache_enabled


def normalize(text: str) -> str:
    """Trim, collapse internal whitespace to single spaces, and NFKC-fold."""
    return unicodedata.normalize("NFKC", " ".join(text.split()))


def _digest(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _vec_digest(vec: list[float]) -> str:
    return hashlib.sha256(json.dumps(vec).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


def get_corpus_version(show_id: uuid.UUID | str) -> int:
    """Current per-show corpus version (0 when unset or on any failure)."""
    try:
        raw = _get_redis().get(_CORPUS_VER_KEY.format(show_id=show_id))
        return int(raw) if raw is not None else 0
    except Exception:
        logger.warning("rag_cache.get_corpus_version failed", exc_info=True)
        return 0


def bump_corpus_version(show_id: uuid.UUID | str) -> None:
    """Increment a show's corpus version, invalidating its cached results.

    Called when a transcription completes or an ASR correction is applied to
    existing episodes (the corpus text / embeddings changed). Fail-open: a
    failed bump only means slightly-stale cache until the fallback TTL expires.
    """
    try:
        _get_redis().incr(_CORPUS_VER_KEY.format(show_id=show_id))
    except Exception:
        logger.warning("rag_cache.bump_corpus_version failed", exc_info=True)


def compute_config_version() -> str:
    """Hash the runtime-tunable settings that affect retrieval output.

    HyDE changes the query embedding (already in the retrieval key) and routing
    flags change ``episode_id_filter`` (also in the key); they are included here
    too so the cache invalidates conservatively whenever an admin toggles them.
    """
    return _digest(
        dict(rag_config.RRF_WEIGHTS),
        settings.enable_hyde_retrieval,
        settings.enable_topic_routing_nudge,
        settings.enable_transcript_topic_prefilter,
        settings.transcript_prefilter_cap,
        os.getenv("ENABLE_TWO_LAYER_ROUTING", "false").strip().lower(),
        bool(settings.voyage_api_key),
    )[:16]


# ---------------------------------------------------------------------------
# Embedding cache (query path)
# ---------------------------------------------------------------------------


def _emb_key(text: str, model: str) -> str:
    return f"emb:{CACHE_SCHEMA_VERSION}:{model}:{_digest(normalize(text))}"


def get_embedding(text: str, model: str) -> list[float] | None:
    if not _enabled():
        return None
    try:
        raw = _get_redis().get(_emb_key(text, model))
        return json.loads(raw) if raw is not None else None
    except Exception:
        logger.warning("rag_cache.get_embedding failed", exc_info=True)
        return None


def set_embedding(text: str, model: str, vector: list[float]) -> None:
    if not _enabled():
        return
    try:
        _get_redis().set(
            _emb_key(text, model),
            json.dumps(vector),
            ex=settings.rag_cache_ttl_seconds,
        )
    except Exception:
        logger.warning("rag_cache.set_embedding failed", exc_info=True)


# ---------------------------------------------------------------------------
# Retrieval cache (retrieve_hybrid output — ChunkHit list)
# ---------------------------------------------------------------------------


def _hit_to_dict(hit: ChunkHit) -> dict:
    return dataclasses.asdict(hit)


def _dict_to_hit(d: dict) -> ChunkHit:
    kwargs: dict[str, Any] = {}
    for name in _HIT_FIELDS:
        if name not in d:
            continue  # missing field -> dataclass default (forward-compatible)
        value = d[name]
        if name in _HIT_UUID_FIELDS and isinstance(value, str):
            value = uuid.UUID(value)
        kwargs[name] = value
    return ChunkHit(**kwargs)


def retrieval_key(
    show_id: uuid.UUID | str,
    question: str,
    query_embedding: list[float],
    k: int,
    episode_id_filter: list[uuid.UUID] | None,
    metadata_filters: Any | None,
) -> str:
    filt = sorted(str(e) for e in (episode_id_filter or []))
    corpus_ver = get_corpus_version(show_id)
    config_ver = compute_config_version()
    digest = _digest(
        question,
        _vec_digest(query_embedding),
        k,
        filt,
        repr(metadata_filters),
    )
    return f"ret:{CACHE_SCHEMA_VERSION}:{show_id}:{corpus_ver}:{config_ver}:{digest}"


def search_response_key(
    show_id: uuid.UUID | str,
    question: str,
    query_embedding: list[float],
    k: int,
    episode_id_filter: list[uuid.UUID] | None,
    metadata_filters: Any | None,
) -> str:
    """Key for the /search endpoint's *enriched* response cache.

    Distinct namespace from ``retrieval_key`` so a hit can skip both
    retrieve_hybrid AND enrich_hits (the latter is the latency bottleneck — it
    runs O(k) per-hit SQL). The service-layer ``retrieval_key`` cache is kept
    separately so the chat agent's tools still benefit from cached retrieval.
    """
    return "search:" + retrieval_key(
        show_id, question, query_embedding, k, episode_id_filter, metadata_filters
    )


def get_retrieval(key: str) -> list[ChunkHit] | None:
    if not _enabled():
        return None
    try:
        raw = _get_redis().get(key)
        if raw is None:
            return None
        return [_dict_to_hit(d) for d in json.loads(raw)]
    except Exception:
        logger.warning("rag_cache.get_retrieval failed", exc_info=True)
        return None


def set_retrieval(key: str, hits: list[ChunkHit]) -> None:
    if not _enabled():
        return
    try:
        payload = json.dumps([_hit_to_dict(h) for h in hits], default=str)
        _get_redis().set(key, payload, ex=settings.rag_cache_ttl_seconds)
    except Exception:
        logger.warning("rag_cache.set_retrieval failed", exc_info=True)


# ---------------------------------------------------------------------------
# Keyword cache (sectioned T1/T2/T3 response dict)
# ---------------------------------------------------------------------------


def keyword_key(
    show_id: uuid.UUID | str,
    query: str,
    collapse_threshold: int,
    offset_t1: int,
    offset_t2: int,
    limit: int,
) -> str:
    # Pagination offsets / limit slice the result server-side, so they must be
    # part of the key — otherwise a "next page" request would hit a prior
    # page's cached slice.
    corpus_ver = get_corpus_version(show_id)
    digest = _digest(normalize(query), collapse_threshold, offset_t1, offset_t2, limit)
    return f"kw:{CACHE_SCHEMA_VERSION}:{show_id}:{corpus_ver}:{digest}"


def get_keyword(key: str) -> dict | None:
    if not _enabled():
        return None
    try:
        raw = _get_redis().get(key)
        return json.loads(raw) if raw is not None else None
    except Exception:
        logger.warning("rag_cache.get_keyword failed", exc_info=True)
        return None


def set_keyword(key: str, response: dict) -> None:
    if not _enabled():
        return
    try:
        _get_redis().set(
            key, json.dumps(response, default=str), ex=settings.rag_cache_ttl_seconds
        )
    except Exception:
        logger.warning("rag_cache.set_keyword failed", exc_info=True)


# ---------------------------------------------------------------------------
# P2 semantic cache machinery (flag-gated, disabled by default)
# ---------------------------------------------------------------------------


def _semantic_active() -> bool:
    return _enabled() and settings.enable_semantic_cache


def _query_quality_ok(text: str) -> bool:
    """Exclude underspecified / punctuation-only / whitespace-only queries."""
    t = normalize(text)
    if len(t) < SEMANTIC_MIN_QUERY_CHARS:
        return False
    if not any(ch.isalnum() for ch in t):
        return False
    return True


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def semantic_lookup(
    show_id: uuid.UUID | str, query_embedding: list[float], query_text: str
) -> dict | None:
    """Return ``{"hits": [...], "similarity": float}`` or ``None``.

    Disabled (the default) → always ``None`` with no Redis access. When
    enabled, scans this show's recent query embeddings for a cosine ≥
    ``settings.semantic_cache_threshold`` and returns the associated cached
    retrieval. Low-quality queries are excluded.
    """
    if not _semantic_active():
        return None
    if not _query_quality_ok(query_text):
        return None
    try:
        entries = _get_redis().lrange(
            _SEM_LIST_KEY.format(show_id=show_id), 0, -1
        )
        best_rec = None
        best_sim = 0.0
        for raw in entries:
            rec = json.loads(raw)
            sim = _cosine(query_embedding, rec["vec"])
            if sim > best_sim:
                best_sim = sim
                best_rec = rec
        if best_rec is not None and best_sim >= settings.semantic_cache_threshold:
            hits = get_retrieval(best_rec["ret_key"])
            if hits is not None:
                return {"hits": hits, "similarity": best_sim}
        return None
    except Exception:
        logger.warning("rag_cache.semantic_lookup failed", exc_info=True)
        return None


def semantic_store(
    show_id: uuid.UUID | str,
    query_embedding: list[float],
    query_text: str,
    ret_key: str,
) -> None:
    """Record a query embedding → retrieval-key mapping for semantic lookup.

    No-op when the semantic cache is disabled or the query is low quality.
    """
    if not _semantic_active():
        return
    if not _query_quality_ok(query_text):
        return
    try:
        r = _get_redis()
        key = _SEM_LIST_KEY.format(show_id=show_id)
        r.lpush(key, json.dumps({"vec": query_embedding, "ret_key": ret_key}))
        r.ltrim(key, 0, _SEM_LIST_CAP - 1)
        r.expire(key, settings.rag_cache_ttl_seconds)
    except Exception:
        logger.warning("rag_cache.semantic_store failed", exc_info=True)
