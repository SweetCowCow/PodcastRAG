"""Keyword (索引) search endpoint.

`POST /shows/{show_id}/keyword-search` — strict-AND multi-term lexical search
over a single show, returning sectioned T1 / T2 / T3 results. Public endpoint
gated by the same per-IP daily rate limit as `/shows/{show_id}/search`; it does
not hit an LLM and does not decrement quota.

Part of change `keyword-index-mode`.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import optional_auth_with_ip_limit
from app.models.app_settings import AppSettings
from app.models.show import Show
from app.models.user import User
from app.schemas.errors import ErrorResponse
from app.schemas.keyword_search import KeywordSearchRequest, KeywordSearchResponse
from app.services import keyword_search, rag_cache

router = APIRouter(tags=["keyword-search"])

_SETTINGS_SINGLETON_ID = 1


async def _get_collapse_threshold(db: AsyncSession) -> int:
    """Read the admin-tunable T2 collapse threshold (falls back to default)."""
    row = await db.get(AppSettings, _SETTINGS_SINGLETON_ID)
    if row is None:
        return keyword_search.DEFAULT_T2_COLLAPSE_THRESHOLD
    return row.keyword_t2_collapse_threshold


@router.post(
    "/shows/{show_id}/keyword-search", response_model=KeywordSearchResponse
)
async def keyword_search_show(
    show_id: uuid.UUID,
    payload: KeywordSearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(optional_auth_with_ip_limit),
) -> KeywordSearchResponse:
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error_code="SHOW_NOT_FOUND", detail="Show 不存在"
            ).model_dump(),
        )

    threshold = await _get_collapse_threshold(db)

    # r4-rag-result-cache: serve identical keyword queries from cache. The key
    # embeds the show's corpus version and the collapse threshold, so re-
    # transcription / ASR backfill / threshold changes self-invalidate.
    # Pagination offsets are request-time slicing the client applies on top, so
    # the cache stores the full sectioned result keyed by query + threshold.
    cache_key = rag_cache.keyword_key(
        show_id,
        payload.query,
        threshold,
        payload.offset_t1,
        payload.offset_t2,
        payload.limit,
    )
    cached = rag_cache.get_keyword(cache_key)
    if cached is not None:
        result = KeywordSearchResponse.model_validate(cached)
        result.cache_hit = True
        return result

    try:
        response = await keyword_search.run_keyword_search(
            db,
            show_id,
            payload.query,
            offset_t1=payload.offset_t1,
            offset_t2=payload.offset_t2,
            limit=payload.limit,
            threshold=threshold,
        )
    except keyword_search.EmptyKeywordQueryError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ErrorResponse(
                error_code="EMPTY_QUERY", detail="查詢經斷詞後沒有可用的關鍵字"
            ).model_dump(),
        )
    except keyword_search.KeywordSearchTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ErrorResponse(
                error_code="KEYWORD_SEARCH_TIMEOUT",
                detail="搜尋逾時，請縮短關鍵字",
            ).model_dump(),
        )

    rag_cache.set_keyword(cache_key, response)
    result = KeywordSearchResponse.model_validate(response)
    result.cache_hit = False
    return result
