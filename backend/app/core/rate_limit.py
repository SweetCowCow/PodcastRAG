"""Per-IP daily rate limit for the public segment-search endpoint.

Implementation: Redis INCR counter keyed by ``rl:search:ip:{client_ip}:{YYYYMMDD}``
with EXPIRE 86400s on first hit. Anonymous callers exceeding the threshold
get HTTP 429 ip_rate_limited; authenticated users skip this check entirely.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import redis
from fastapi import Request

from app.core.config import settings

DAILY_TTL_SECONDS = 86_400
KEY_PREFIX = "rl:search:ip"


@lru_cache(maxsize=1)
def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.celery_broker_url)


def client_ip(request: Request) -> str:
    """Resolve client IP, honoring X-Forwarded-For first hop."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client is not None:
        return request.client.host or "unknown"
    return "unknown"


def _today_key(ip: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{KEY_PREFIX}:{ip}:{now.strftime('%Y%m%d')}"


def _next_utc_midnight(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    next_day = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return next_day.strftime("%Y-%m-%dT%H:%M:%SZ")


def check_ip_search_limit(ip: str, limit: int | None = None) -> tuple[int, bool]:
    """Increment the IP counter and report (count, exceeded).

    Returns (current_count_after_increment, exceeded_flag). Sets EXPIRE on
    the first hit so the key auto-clears after 24h. The caller decides what
    to do when exceeded (raise 429 in the FastAPI dependency).
    """
    if limit is None:
        limit = settings.ip_search_rate_limit_per_day
    r = _get_redis()
    key = _today_key(ip)
    count = r.incr(key)
    if count == 1:
        r.expire(key, DAILY_TTL_SECONDS)
    exceeded = count > limit
    return count, exceeded


MINUTE_TTL_SECONDS = 60
MINUTE_KEY_PREFIX = "rl:min:ip"


def _minute_key(prefix: str, ip: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{MINUTE_KEY_PREFIX}:{prefix}:{ip}:{now.strftime('%Y%m%d%H%M')}"


def check_ip_minute_limit(
    ip: str, *, prefix: str, limit: int
) -> tuple[int, bool]:
    """Per-minute INCR counter (60s TTL). Returns (count_after, exceeded)."""
    r = _get_redis()
    key = _minute_key(prefix, ip)
    count = r.incr(key)
    if count == 1:
        r.expire(key, MINUTE_TTL_SECONDS)
    return count, count > limit


def rate_limit_error_payload(limit: int) -> dict:
    """Structured 429 body matching the ip-rate-limit spec."""
    return {
        "error_code": "ip_rate_limited",
        "detail": "已達今日免費搜尋上限，請登入繼續使用",
        "limit": limit,
        "reset_at_utc": _next_utc_midnight(),
    }
