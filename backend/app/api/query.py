import asyncio
import uuid

import openai
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_authenticated_user
from app.models.show import Show
from app.models.user import User
from app.schemas.errors import ErrorCode, ErrorResponse
from app.schemas.query import (
    ChatResponse,
    ChunkHit,
    QueryRequest,
    SearchResponse,
)
from app.services import rag
from app.services.embedding import embed_texts
from app.services.llm_config import (
    LLMNotConfigured,
    get_answer_client,
    get_config,
    get_rewrite_client,
    infer_provider_label,
    require_keys_present,
)
from app.services.rag import ChunkHit as RagHit

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


@router.post("/shows/{show_id}/query")
async def query_show(
    show_id: uuid.UUID,
    payload: QueryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
) -> SearchResponse | ChatResponse:
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    # Atomically decrement quota BEFORE any LLM/embedding call. If subsequent
    # RAG calls fail, we do NOT refund (see design: 失敗成本權衡).
    quota_remaining = await _atomic_decrement_quota(db, user.id)

    history = [m.model_dump() for m in payload.messages[-rag.HISTORY_WINDOW:]]

    if payload.mode == "search":
        try:
            query_embedding = await asyncio.to_thread(embed_texts, [payload.question])
        except (
            openai.RateLimitError,
            openai.AuthenticationError,
            openai.APIConnectionError,
            openai.APITimeoutError,
        ) as exc:
            _raise_openai_http_error(exc, "OpenAI")
        hits = await rag.retrieve(db, show_id, query_embedding[0])
        return SearchResponse(
            results=[_to_schema_hit(h) for h in hits],
            quota_remaining=quota_remaining,
        )

    try:
        cfg = await get_config(db)
        require_keys_present(cfg)
    except LLMNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error_code=ErrorCode.LLM_NOT_CONFIGURED,
                provider=None,
                detail=str(exc),
            ).model_dump(),
        ) from exc

    if history:
        rewrite_client, rewrite_model = get_rewrite_client(cfg)
        try:
            rewritten = await asyncio.to_thread(
                rag.rewrite_question,
                rewrite_client,
                rewrite_model,
                history,
                payload.question,
            )
        except (
            openai.RateLimitError,
            openai.AuthenticationError,
            openai.APIConnectionError,
            openai.APITimeoutError,
        ) as exc:
            _raise_openai_http_error(exc, infer_provider_label(cfg.rewrite_base_url))
    else:
        rewritten = payload.question

    try:
        query_embedding = await asyncio.to_thread(embed_texts, [rewritten])
    except (
        openai.RateLimitError,
        openai.AuthenticationError,
        openai.APIConnectionError,
        openai.APITimeoutError,
    ) as exc:
        _raise_openai_http_error(exc, "OpenAI")
    hits = await rag.retrieve(db, show_id, query_embedding[0])

    answer_client, answer_model = get_answer_client(cfg)
    try:
        answer_text, used_ids = await asyncio.to_thread(
            rag.answer_with_chunks,
            answer_client,
            answer_model,
            history,
            payload.question,
            hits,
        )
    except (
        openai.RateLimitError,
        openai.AuthenticationError,
        openai.APIConnectionError,
        openai.APITimeoutError,
    ) as exc:
        _raise_openai_http_error(exc, infer_provider_label(cfg.answer_base_url))

    if used_ids:
        used_set = set(used_ids)
        cited_hits = [
            h for h in hits
            if f"ep:{h.episode_id}@{h.start_time:.2f}" in used_set
        ]
        if not cited_hits:
            cited_hits = hits
    else:
        cited_hits = hits

    return ChatResponse(
        answer=answer_text,
        citations=[_to_schema_hit(h) for h in cited_hits],
        quota_remaining=quota_remaining,
    )


def _to_schema_hit(hit: RagHit) -> ChunkHit:
    return ChunkHit(
        episode_id=hit.episode_id,
        episode_title=hit.episode_title,
        start_time=hit.start_time,
        end_time=hit.end_time,
        text=hit.text,
        distance=hit.distance,
    )
