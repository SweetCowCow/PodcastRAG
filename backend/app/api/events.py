"""Generic client event ingestion + trending-queries aggregation.

Supports event_types:
  - `citation_click` (R1.1 v1, QueryPage SourceCard)
  - `search_executed` (landing-and-mode-orchestration-redesign, QueryPage
    semantic/chat after successful response)

Public endpoints with per-IP rate limit (60/min). Logged-in sessions tag
rows with user_id; anonymous rows store NULL.
"""
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import check_ip_minute_limit, client_ip
from app.core.security import SESSION_COOKIE
from app.models.event import Event
from app.models.show import Show
from app.models.user import User, UserStatus
from app.schemas.event import EventCreate

router = APIRouter(tags=["events"])

EVENTS_PER_MIN_LIMIT = 60
TRENDING_CUTOFF = int(os.environ.get("TRENDING_QUERIES_CUTOFF", "3"))
TRENDING_MAX_RETURN = 10


async def _resolve_optional_user(
    db: AsyncSession, session_id: str | None
) -> User | None:
    if not session_id:
        return None
    from sqlalchemy import select

    from app.services.session_service import resolve_session

    session_row = await resolve_session(db, session_id)
    if session_row is None:
        return None
    user = (
        await db.execute(select(User).where(User.id == session_row.user_id))
    ).scalar_one_or_none()
    if user is None or user.status == UserStatus.disabled.value:
        return None
    return user


@router.post("/events", status_code=202)
async def post_event(
    payload: EventCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Response:
    ip = client_ip(request)
    _count, exceeded = check_ip_minute_limit(
        ip, prefix="events", limit=EVENTS_PER_MIN_LIMIT
    )
    if exceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "ip_rate_limited",
                "detail": "events rate limit exceeded",
                "limit": EVENTS_PER_MIN_LIMIT,
            },
        )

    user = await _resolve_optional_user(db, session_id)

    row = Event(
        event_type=payload.event_type,
        event_payload=payload.payload.model_dump(),
        user_id=user.id if user is not None else None,
    )
    db.add(row)
    await db.commit()
    response.status_code = 202
    return response


_TRENDING_SQL = """
SELECT event_payload->>'query_text' AS query_text, COUNT(*) AS cnt
FROM events
WHERE event_type = 'search_executed'
  AND created_at >= NOW() - (:days || ' days')::interval
  AND event_payload->>'show_id' = :show_id
GROUP BY event_payload->>'query_text'
HAVING COUNT(*) >= :cutoff
ORDER BY cnt DESC
LIMIT :limit
"""


@router.get("/shows/{show_id}/trending-queries")
async def get_trending_queries(
    show_id: uuid.UUID,
    request: Request,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """landing-and-mode-orchestration-redesign: return popular search_executed
    query strings per show for the last `days` days (default 7), grouped by
    query_text, only returning groups with count >= TRENDING_QUERIES_CUTOFF
    (default 3), ordered by count descending, up to 10 entries.
    """
    ip = client_ip(request)
    _count, exceeded = check_ip_minute_limit(
        ip, prefix="events", limit=EVENTS_PER_MIN_LIMIT
    )
    if exceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "ip_rate_limited",
                "detail": "events rate limit exceeded",
                "limit": EVENTS_PER_MIN_LIMIT,
            },
        )

    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="show not found")

    result = await db.execute(
        text(_TRENDING_SQL),
        {
            "days": str(days),
            "show_id": str(show_id),
            "cutoff": TRENDING_CUTOFF,
            "limit": TRENDING_MAX_RETURN,
        },
    )
    rows = result.mappings().all()
    return {
        "queries": [
            {"query_text": r["query_text"], "count": int(r["cnt"])} for r in rows
        ],
        "days": days,
        "cutoff": TRENDING_CUTOFF,
    }
