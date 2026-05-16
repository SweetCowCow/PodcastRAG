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

from app.services import citation_parser, episode_finders, query_entity, rag
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
# enumeration response" lists 哪幾集 / 哪集 / 哪些集 — but Traditional
# Chinese users routinely type 那 (that) where 哪 (which) is meant
# (homophones, both pronounced 'na'). Prod verification 2026-05-16 caught
# 「歌單那幾集講過什麼」 silently dropping out of the enumeration path,
# so the trigger accepts both characters.
_ENUMERATION_RULE_PATTERN = re.compile(r"[哪那]幾集|[哪那]集|[哪那]些集")

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


async def _compute_enumeration_episodes(
    db: AsyncSession,
    show_id: uuid.UUID,
    question: str,
    entities: QueryEntities,
) -> tuple[list[EpisodeRef] | None, str]:
    """Build the `enumeration_episodes` list for an enumeration query.

    R3.3 + r3-3-chat-enum-grounding: dispatches to the tool-like finder
    functions in `app.services.episode_finders` and combines results.

    Trigger (any one fires the path):
      - `entities.guests` non-empty
      - `entities.date_range` non-empty
      - `entities.topics` non-empty
      - question matches `[哪那]幾集 / [哪那]集 / [哪那]些集` rule pattern
        (and the question itself becomes the topic-term source via jieba)

    Combination semantics:
      - guests + topics both non-empty → AND-intersect by episode_id;
        empty intersection → fallback to guests-only (returns
        fallback_marker = "guest_only") so the answer prompt can warn
        the user that no episode satisfied both constraints.
      - guests + date_range both → AND-intersect (no fallback today).
      - topics + date_range → AND-intersect.
      - rule pattern matched but every entities field empty → use
        `extract_topic_terms_from_question(question)` as topic_terms and
        run the topic finder. We no longer fall back to "list every
        episode in the show".

    Returns:
      (episodes_or_None, fallback_marker)
        - episodes_or_None is `None` when no trigger matched (callers
          should set enumeration_episodes / enumeration_total to None),
          empty list when trigger matched but 0 episodes survived
          filtering, populated list otherwise.
        - fallback_marker is one of "none" (no fallback applied) or
          "guest_only" (AND was empty, fell back to guests-only).
    """
    rule_match = bool(_ENUMERATION_RULE_PATTERN.search(question or ""))
    has_guests = bool(entities.guests)
    has_date = entities.date_range is not None
    has_topics = bool(entities.topics)
    if not (has_guests or has_date or has_topics or rule_match):
        return None, "none"

    # Collect results from each entity-driven finder. We invoke at most
    # three SQL roundtrips; combine in Python by episode_id.
    guest_eps: list[EpisodeRef] | None = None
    topic_eps: list[EpisodeRef] | None = None
    date_eps: list[EpisodeRef] | None = None

    if has_guests:
        guest_eps = await episode_finders.find_episodes_by_guest(
            db, show_id, list(entities.guests)
        )
    if has_topics:
        topic_eps = await episode_finders.find_episodes_by_topic(
            db, show_id, list(entities.topics)
        )
    if has_date:
        start, end = entities.date_range
        date_eps = await episode_finders.find_episodes_by_date_range(
            db, show_id, start, end
        )

    # Rule-pattern-only path: derive topic_terms from the question itself.
    # Only kicks in when the LLM extracted nothing usable; otherwise the
    # entity-driven results above already covered the intent.
    if rule_match and guest_eps is None and topic_eps is None and date_eps is None:
        terms = episode_finders.extract_topic_terms_from_question(question)
        topic_eps = await episode_finders.find_episodes_by_topic(
            db, show_id, terms
        )

    # Combine. AND-intersect every non-None group.
    fallback_marker = "none"
    groups = [g for g in (guest_eps, topic_eps, date_eps) if g is not None]
    if not groups:
        # All triggers fired but every finder declined (e.g. empty
        # rule-pattern terms after stopword filter). Surface empty list.
        return [], "none"

    if len(groups) == 1:
        combined = groups[0]
    else:
        # Intersect by episode_id, preserve first group's ordering.
        common_ids = set(e.episode_id for e in groups[0])
        for g in groups[1:]:
            common_ids &= set(e.episode_id for e in g)
        combined = [e for e in groups[0] if e.episode_id in common_ids]

    # AND-with-fallback: if guest+topic intersected to nothing, fall
    # back to guest-only (date_range stays AND if present — date is a
    # hard temporal scope, not a soft filter we should drop).
    if not combined and has_guests and has_topics and guest_eps:
        # Preserve any date_range filter on the fallback set.
        if date_eps is not None:
            date_ids = {e.episode_id for e in date_eps}
            combined = [e for e in guest_eps if e.episode_id in date_ids]
        else:
            combined = list(guest_eps)
        if combined:
            fallback_marker = "guest_only"

    return combined, fallback_marker


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

    enumeration, fallback_marker = await _compute_enumeration_episodes(
        db, show_id, rewritten, entities
    )
    enumeration_total = len(enumeration) if enumeration is not None else None
    # Build the grounding block when enumeration was triggered (None = not
    # triggered; [] = triggered but 0 matches). Both cases produce a block,
    # but the empty case uses a "沒有找到相符的集數" header so the answer
    # model knows there was a real filter that returned nothing.
    enumeration_block = (
        rag.format_enumeration_block(
            episodes=enumeration,
            total=enumeration_total or 0,
            fallback_marker=fallback_marker,
            entities=entities,
        )
        if enumeration is not None
        else None
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
            enumeration_block,
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
        enumeration_total=enumeration_total,
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
