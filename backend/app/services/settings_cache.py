"""In-process cache for runtime-tunable app settings.

Source of truth: ``app_settings`` table. To avoid every dispatcher tick or
``transcribe_episode`` invocation re-reading the DB, the
``PUT /admin/settings`` endpoint publishes the new value to a Redis key
which sync (Celery worker) and async (dispatcher) callers both read,
fronted by a short-TTL in-process cache.
"""
from functools import lru_cache

import redis
from cachetools import TTLCache

from app.core.config import settings

REDIS_KEY = "transcribe:settings:max_concurrent"
DEFAULT_MAX_CONCURRENT = 1
CACHE_TTL_SECONDS = 60

_cache: TTLCache = TTLCache(maxsize=4, ttl=CACHE_TTL_SECONDS)


@lru_cache(maxsize=1)
def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.celery_broker_url)


def get_max_concurrent() -> int:
    """Return the current max concurrent transcriptions (sync, cached 60s)."""
    cached = _cache.get(REDIS_KEY)
    if cached is not None:
        return cached
    raw = _get_redis().get(REDIS_KEY)
    value = int(raw) if raw is not None else DEFAULT_MAX_CONCURRENT
    _cache[REDIS_KEY] = value
    return value


def publish_max_concurrent(value: int) -> None:
    """Called by ``PUT /admin/settings`` after writing to DB."""
    _get_redis().set(REDIS_KEY, int(value))
    _cache.pop(REDIS_KEY, None)


def invalidate() -> None:
    _cache.clear()
