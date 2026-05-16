import asyncio
import json as _stdlib_json
import logging
import re
import uuid

import openai
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import optional_auth_with_ip_limit, require_authenticated_user
from app.models.show import Show
from app.models.user import User
from app.schemas.errors import ErrorCode, ErrorResponse
from app.schemas.query import (
    ChatResponse,
    ChunkHit,
    EpisodeRef,
    PublicSearchRequest,
    PublicSearchResponse,
    QueryRequest,
    SearchResponse,
    SentenceCitations,
)
from app.schemas.query_entity import QueryEntities
from openai import AsyncOpenAI, OpenAI

from app.services import citation_parser, query_entity, rag
from app.services.ai_step_resolver import (
    AiStepNotConfiguredError,
    get_step_config,
    infer_provider_label,
)
from app.services.embedding import embed_texts
from app.services.rag import ChunkHit as RagHit, MetadataFilters

logger = logging.getLogger(__name__)

# R3.3 Phase 9: substring trigger for the enumeration UI when the entity
# extractor returns empty. Spec scenario "Enumeration rule pattern triggers
# enumeration response" lists these three substrings.
_ENUMERATION_RULE_PATTERN = re.compile(r"哪幾集|哪集|哪些集")

router = APIRouter(tags=["query"])


def _is_insufficient_quota(exc: openai.RateLimitError) -> bool:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("code") == "insufficient_quota":
            return True
    return False


def _raise_openai_http_error(exc: Exception, provider_label: str) -> None:
    """Convert an OpenAI client exception into an HTTPException with ErrorResponse detail."""
    if isinstance(exc, openai.RateLimitError):
        code = (
            ErrorCode.LLM_QUOTA_EXCEEDED
            if _is_insufficient_quota(exc)
            else ErrorCode.LLM_RATE_LIMITED
        )
        raise HTTPException(
            status_code=429,
            detail=ErrorResponse(
                error_code=code,
                provider=provider_label,
                detail=str(exc) or "LLM rate limit",
            ).model_dump(),
        ) from exc
    if isinstance(exc, openai.AuthenticationError):
        raise HTTPException(
            status_code=502,
            detail=ErrorResponse(
                error_code=ErrorCode.LLM_AUTH_FAILED,
                provider=provider_label,
                detail=str(exc) or "LLM authentication failed",
            ).model_dump(),
        ) from exc
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse(
                error_code=ErrorCode.LLM_UNAVAILABLE,
                provider=provider_label,
                detail=str(exc) or "LLM unavailable",
            ).model_dump(),
        ) from exc
    raise exc


async def _atomic_decrement_quota(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Atomically decrement the user's quota. Returns the new remaining value.

    Raises HTTPException(429) if quota_remaining was already 0.
    Per design: failure after this call does NOT refund quota — admin can top up.
    """
    stmt = (
        update(User)
        .where(User.id == user_id, User.quota_remaining > 0)
        .values(
            quota_remaining=User.quota_remaining - 1,
            total_queries=User.total_queries + 1,
        )
        .returning(User.quota_remaining)
    )
    result = await db.execute(stmt)
    new_remaining = result.scalar_one_or_none()
    await db.commit()
    if new_remaining is None:
        raise HTTPException(
            status_code=429,
            detail=ErrorResponse(
                error_code=ErrorCode.QUOTA_EXHAUSTED,
                provider=None,
                detail="Query quota exhausted",
            ).model_dump(),
        )
    return int(new_remaining)


@router.post("/shows/{show_id}/search", response_model=PublicSearchResponse)
async def public_search_show(
    show_id: uuid.UUID,
    payload: PublicSearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(optional_auth_with_ip_limit),
) -> PublicSearchResponse:
    """Public-search endpoint: returns top-K matching segments only.

    - Anonymous callers: gated by per-IP daily rate limit (raises 429 over).
    - Authenticated callers: bypass the IP limit; do NOT decrement quota.
    The cost ceiling is the per-call embedding spend; the IP limit caps anonymous,
    and the chat endpoint's quota gate caps authenticated.
    """
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    try:
        embedding_cfg = await get_step_config(db, "embedding")
    except AiStepNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error_code=ErrorCode.LLM_NOT_CONFIGURED,
                provider=None,
                detail=str(exc),
            ).model_dump(),
        ) from exc

    try:
        query_embedding = await asyncio.to_thread(
            embed_texts, [payload.question], embedding_cfg
        )
    except (
        openai.RateLimitError,
        openai.AuthenticationError,
        openai.APIConnectionError,
        openai.APITimeoutError,
    ) as exc:
        _raise_openai_http_error(exc, "OpenAI")

    routed_eps = (
        None
        if rag._should_skip_routing(payload.question)
        else await rag.route_episodes(db, show_id, query_embedding[0])
    )
    hits = await rag.retrieve_hybrid(
        db,
        show_id,
        query_embedding[0],
        payload.question,
        k=payload.k,
        episode_id_filter=routed_eps,
    )
    await rag.enrich_hits(db, hits, payload.question)
    return PublicSearchResponse(results=[_to_schema_hit(h) for h in hits])


def _entities_to_metadata_filters(entities: QueryEntities) -> MetadataFilters | None:
    """Lift `QueryEntities` into the rag-side `MetadataFilters` (guests +
    date_range only). Returns None when there is nothing to filter on, so
    callers can fall through to no-filter retrieval (fail-open path).
    """
    if not entities.guests and entities.date_range is None:
        return None
    return MetadataFilters(
        guests=list(entities.guests),
        date_range=entities.date_range,
    )


async def _extract_entities_fail_open(
    db: AsyncSession, question: str
) -> QueryEntities:
    """Best-effort wrapper around `query_entity.extract_entities`.

    Per R3.3 spec "Entity extraction fails-open without breaking retrieval":
    every failure path — step not configured, client construction, LLM
    error, schema mismatch — returns `QueryEntities.empty()` so retrieval
    proceeds with no metadata filter. The chat endpoint MUST NOT 5xx
    because entity extraction failed.
    """
    try:
        entity_cfg = await get_step_config(db, "entity_extraction")
    except AiStepNotConfiguredError as exc:
        logger.warning("entity_extraction step not configured; fail-open: %s", exc)
        return QueryEntities.empty()
    try:
        client = AsyncOpenAI(base_url=entity_cfg.base_url, api_key=entity_cfg.api_key)
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("entity_extraction AsyncOpenAI ctor failed; fail-open: %s", exc)
        return QueryEntities.empty()
    entities, _status = await query_entity.extract_entities(
        client, model=entity_cfg.model, question=question
    )
    return entities


_ENUMERATION_SQL_BASE = """
SELECT id, title, published_at, guests, ai_summary
FROM episodes
WHERE show_id = :show_id
"""


async def _compute_enumeration_episodes(
    db: AsyncSession,
    show_id: uuid.UUID,
    question: str,
    entities: QueryEntities,
) -> list[EpisodeRef] | None:
    """Build the `enumeration_episodes` list when the question is an
    enumeration-type query (R3.3 Phase 9 / Decision 4).

    Trigger:
      - non-empty `entities.guests` OR `entities.date_range`, OR
      - question contains the enumeration rule substring `哪幾集/哪集/哪些集`

    Filters: guests `@>` containment, published_at BETWEEN endpoints.
    When the trigger is rule-pattern-only (no entity filter) the SQL has
    no extra WHERE clauses — the response lists every episode of the show
    sorted by `published_at DESC`, matching the spec scenario "rule pattern
    triggers enumeration response".

    Returns None when no trigger matched.
    """
    rule_match = bool(_ENUMERATION_RULE_PATTERN.search(question or ""))
    has_entity = bool(entities.guests) or entities.date_range is not None
    if not has_entity and not rule_match:
        return None

    params: dict = {"show_id": show_id}
    extra_clauses: list[str] = []
    if entities.guests:
        extra_clauses.append("guests @> CAST(:enum_guests AS jsonb)")
        params["enum_guests"] = _stdlib_json.dumps(entities.guests)
    if entities.date_range is not None:
        extra_clauses.append(
            "published_at BETWEEN :enum_date_start AND :enum_date_end"
        )
        params["enum_date_start"] = entities.date_range[0]
        params["enum_date_end"] = entities.date_range[1]
    sql_str = _ENUMERATION_SQL_BASE
    for c in extra_clauses:
        sql_str += f"  AND {c}\n"
    sql_str += "ORDER BY published_at DESC NULLS LAST"
    result = await db.execute(text(sql_str), params)
    return [
        EpisodeRef(
            episode_id=row["id"],
            title=row["title"],
            published_at=row["published_at"],
            guests=list(row["guests"] or []),
            ai_summary=row["ai_summary"],
        )
        for row in result.mappings()
    ]


def _resolve_lang(raw: str | None) -> str:
    """Map the `lang` cookie value to either 'zh' or 'en' (default 'zh').

    Per CLAUDE.md the project supports zh / en only; any other value falls
    back to zh so the prompt always renders.
    """
    if raw and raw.lower().startswith("en"):
        return "en"
    return "zh"


@router.post("/shows/{show_id}/query")
async def query_show(
    show_id: uuid.UUID,
    payload: QueryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
    lang: str | None = Cookie(default=None),
) -> SearchResponse | ChatResponse:
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    # Atomically decrement quota BEFORE any LLM/embedding call. If subsequent
    # RAG calls fail, we do NOT refund (see design: 失敗成本權衡).
    quota_remaining = await _atomic_decrement_quota(db, user.id)

    history = [m.model_dump() for m in payload.messages[-rag.HISTORY_WINDOW:]]

    # Embedding step is required for both search and chat modes.
    try:
        embedding_cfg = await get_step_config(db, "embedding")
    except AiStepNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error_code=ErrorCode.LLM_NOT_CONFIGURED,
                provider=None,
                detail=str(exc),
            ).model_dump(),
        ) from exc

    if payload.mode == "search":
        try:
            query_embedding = await asyncio.to_thread(
                embed_texts, [payload.question], embedding_cfg
            )
        except (
            openai.RateLimitError,
            openai.AuthenticationError,
            openai.APIConnectionError,
            openai.APITimeoutError,
        ) as exc:
            _raise_openai_http_error(exc, "OpenAI")
        routed_eps = (
            None
            if rag._should_skip_routing(payload.question)
            else await rag.route_episodes(db, show_id, query_embedding[0])
        )
        hits = await rag.retrieve_hybrid(
            db,
            show_id,
            query_embedding[0],
            payload.question,
            episode_id_filter=routed_eps,
        )
        await rag.enrich_hits(db, hits, payload.question)
        return SearchResponse(
            results=[_to_schema_hit(h) for h in hits],
            quota_remaining=quota_remaining,
        )

    try:
        rewrite_cfg = await get_step_config(db, "rewrite")
        answer_cfg = await get_step_config(db, "answer")
    except AiStepNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error_code=ErrorCode.LLM_NOT_CONFIGURED,
                provider=None,
                detail=str(exc),
            ).model_dump(),
        ) from exc

    if history:
        rewrite_client = OpenAI(
            base_url=rewrite_cfg.base_url, api_key=rewrite_cfg.api_key
        )
        try:
            rewritten = await asyncio.to_thread(
                rag.rewrite_question,
                rewrite_client,
                rewrite_cfg.model,
                history,
                payload.question,
            )
        except (
            openai.RateLimitError,
            openai.AuthenticationError,
            openai.APIConnectionError,
            openai.APITimeoutError,
        ) as exc:
            _raise_openai_http_error(exc, infer_provider_label(rewrite_cfg.base_url))
    else:
        rewritten = payload.question

    try:
        query_embedding = await asyncio.to_thread(
            embed_texts, [rewritten], embedding_cfg
        )
    except (
        openai.RateLimitError,
        openai.AuthenticationError,
        openai.APIConnectionError,
        openai.APITimeoutError,
    ) as exc:
        _raise_openai_http_error(exc, "OpenAI")

    # R3.3 Phase 9: extract entities from the rewritten question for
    # metadata-filter-aware retrieval + cross-episode enumeration. Fail-open:
    # any extractor error → empty entities → no filter, retrieval runs as
    # before.
    entities = await _extract_entities_fail_open(db, rewritten)
    metadata_filters = _entities_to_metadata_filters(entities)

    routed_eps = (
        None
        if rag._should_skip_routing(rewritten)
        else await rag.route_episodes(db, show_id, query_embedding[0])
    )
    hits = await rag.retrieve_hybrid(
        db,
        show_id,
        query_embedding[0],
        rewritten,
        episode_id_filter=routed_eps,
        metadata_filters=metadata_filters,
    )
    await rag.enrich_hits(db, hits, rewritten)

    enumeration = await _compute_enumeration_episodes(
        db, show_id, rewritten, entities
    )

    answer_client = OpenAI(
        base_url=answer_cfg.base_url, api_key=answer_cfg.api_key
    )
    try:
        # R2.1-fix Fix 1: answer_with_chunks now returns (raw, clean, ids).
        # The API serves the raw answer (frontend renders `[N]` brackets via
        # `citation_parser.parse` below); the cleaned form is for eval/judge.
        answer_text, _answer_clean, used_ids = await asyncio.to_thread(
            rag.answer_with_chunks,
            answer_client,
            answer_cfg.model,
            history,
            payload.question,
            hits,
            _resolve_lang(lang),
        )
    except (
        openai.RateLimitError,
        openai.AuthenticationError,
        openai.APIConnectionError,
        openai.APITimeoutError,
    ) as exc:
        _raise_openai_http_error(exc, infer_provider_label(answer_cfg.base_url))

    if used_ids:
        used_set = set(used_ids)
        cited_hits = [h for h in hits if rag._hit_key(h) in used_set]
        if not cited_hits:
            cited_hits = hits
    else:
        cited_hits = hits

    # R2.1 task 3.4: strip invalid `[N]` refs before serialising. The
    # `citations` array (built from used_chunk_ids) is unchanged so the
    # frontend can still render source cards even when no inline refs survive.
    cleaned_answer, meta = citation_parser.parse(answer_text, len(hits))
    citations_meta = [
        SentenceCitations(sentence_index=m.sentence_index, ref_ids=m.ref_ids)
        for m in meta
    ]

    return ChatResponse(
        query_id=uuid.uuid4().hex[:32],
        answer=cleaned_answer,
        citations=[_to_schema_hit(h) for h in cited_hits],
        quota_remaining=quota_remaining,
        citations_meta=citations_meta,
        enumeration_episodes=enumeration,
    )


def _to_schema_hit(hit: RagHit) -> ChunkHit:
    return ChunkHit(
        episode_id=hit.episode_id,
        episode_title=hit.episode_title,
        start_time=hit.start_time,
        end_time=hit.end_time,
        text=hit.text,
        distance=hit.distance,
        source=hit.source,
        before_text=hit.before_text,
        after_text=hit.after_text,
        highlights=hit.highlights,
        ai_summary_excerpt=hit.ai_summary_excerpt,
        ai_summary_full=hit.ai_summary_full,
    )
