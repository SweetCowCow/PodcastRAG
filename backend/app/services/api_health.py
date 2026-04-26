import asyncio
import json
import logging
import time
from functools import lru_cache
from typing import Literal

import httpx
import openai
import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

API_NAMES = ("openai_whisper", "openai_chat", "openai_embedding")
MAX_EVENTS = 20
TTL_SECONDS = 604800  # 7 days

ErrorCategory = Literal[
    "quota_exceeded",
    "rate_limited",
    "auth_error",
    "server_error",
    "network_error",
    "unknown",
]

_KEY_FMT = "api_health:{api_name}"


@lru_cache(maxsize=1)
def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.celery_broker_url)


def _extract_error_code(exc: BaseException) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            if isinstance(code, str):
                return code
    return None


def classify_error(
    exc: BaseException | None, http_status: int | None = None
) -> ErrorCategory:
    if isinstance(exc, openai.RateLimitError):
        if _extract_error_code(exc) == "insufficient_quota":
            return "quota_exceeded"
        return "rate_limited"

    if isinstance(exc, openai.AuthenticationError):
        return "auth_error"
    if http_status in (401, 403):
        return "auth_error"

    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", None)
        if isinstance(status, int) and 500 <= status < 600:
            return "server_error"
    if isinstance(http_status, int) and 500 <= http_status < 600:
        return "server_error"

    if isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.ConnectError,
            asyncio.TimeoutError,
            openai.APIConnectionError,
        ),
    ):
        return "network_error"

    return "unknown"


def record(
    api_name: str,
    ok: bool,
    duration_ms: int,
    error_category: ErrorCategory | None = None,
    http_status: int | None = None,
) -> None:
    """Append a health event for the given api_name. Fail-open on Redis errors."""
    event = {
        "ts_ms": int(time.time() * 1000),
        "ok": bool(ok),
        "duration_ms": int(max(0, duration_ms)),
        "error_category": error_category,
        "http_status": http_status,
    }
    key = _KEY_FMT.format(api_name=api_name)
    try:
        client = _get_redis()
        pipe = client.pipeline()
        pipe.lpush(key, json.dumps(event))
        pipe.ltrim(key, 0, MAX_EVENTS - 1)
        pipe.expire(key, TTL_SECONDS)
        pipe.execute()
    except Exception as exc:  # fail-open: tracker bugs must never break callers
        logger.warning(
            "api_health.record failed for %s: %s", api_name, type(exc).__name__
        )


def get_recent(
    api_name: str, limit: int = MAX_EVENTS
) -> tuple[list[dict], bool]:
    """Return (events_newest_first, degraded). degraded=True if Redis call failed."""
    key = _KEY_FMT.format(api_name=api_name)
    try:
        client = _get_redis()
        raw = client.lrange(key, 0, limit - 1)
    except redis.RedisError as exc:
        logger.warning(
            "api_health.get_recent failed for %s: %s", api_name, type(exc).__name__
        )
        return [], True

    events: list[dict] = []
    for item in raw:
        try:
            events.append(json.loads(item))
        except (ValueError, TypeError):
            continue
    return events, False
