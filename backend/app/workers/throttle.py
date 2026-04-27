from functools import lru_cache

import redis

from app.core.config import settings
from app.services.settings_cache import get_max_concurrent

GLOBAL_ACTIVE_KEY = "transcribe:global:active_count"
GLOBAL_SLOT_KEY = "transcribe:global:slot:{}"
SHOW_LOCK_KEY = "transcribe:show:{}:lock"
GLOBAL_SLOT_TTL = 7200
SHOW_LOCK_TTL = 1800


@lru_cache(maxsize=1)
def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.celery_broker_url)


def acquire_global_slot(task_id: str) -> bool:
    """Try to claim one of the global concurrent transcription slots.

    The cap is read from ``settings_cache.get_max_concurrent`` (DB-backed,
    Redis-published, 60s in-process cache) so the value can be tuned
    without restarting the worker.
    """
    max_concurrent = get_max_concurrent()
    r = _get_redis()
    count = r.incr(GLOBAL_ACTIVE_KEY)
    if count > max_concurrent:
        r.decr(GLOBAL_ACTIVE_KEY)
        return False
    r.set(GLOBAL_SLOT_KEY.format(task_id), 1, ex=GLOBAL_SLOT_TTL)
    return True


def release_global_slot(task_id: str) -> None:
    r = _get_redis()
    count = r.decr(GLOBAL_ACTIVE_KEY)
    if count < 0:
        r.set(GLOBAL_ACTIVE_KEY, 0, xx=True)
    r.delete(GLOBAL_SLOT_KEY.format(task_id))


def acquire_show_lock(show_id: str) -> bool:
    r = _get_redis()
    return bool(r.set(SHOW_LOCK_KEY.format(show_id), 1, nx=True, ex=SHOW_LOCK_TTL))


def release_show_lock(show_id: str) -> None:
    r = _get_redis()
    r.delete(SHOW_LOCK_KEY.format(show_id))
