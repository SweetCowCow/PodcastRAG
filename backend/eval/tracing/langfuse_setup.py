"""Langfuse Cloud (Free tier) SDK initialization for eval trace observability.

Part of change `eval-framework-upgrade` (2026-05-29). See design Decision 1.

Three modes (gated by `Settings.eval_tracing_enabled` and presence of keys):

1. **Disabled** (`EVAL_TRACING_ENABLED=false`, default for prod user traffic):
   `init_langfuse()` returns None, `observe` decorator is a no-op wrapper.
2. **Enabled, keys present**: returns a configured `Langfuse` client connected
   to `LANGFUSE_HOST` (default `https://cloud.langfuse.com`).
3. **Enabled, keys missing**: logs a warning and returns None — calling code
   SHALL treat None as "tracing unavailable, proceed without spans". This
   matches the eval-observability spec scenario "prod user traffic does not
   emit spans by default" and the design Decision 7 fail-safe rule.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from app.core.config import settings

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

_client: Any = None
_initialized: bool = False


def init_langfuse() -> Any | None:
    """Initialize and cache the Langfuse client. Idempotent.

    Returns the client on success, None when disabled or keys missing.
    """
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    if not settings.eval_tracing_enabled:
        logger.debug("langfuse: EVAL_TRACING_ENABLED=false, tracing disabled")
        _client = None
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning(
            "langfuse: EVAL_TRACING_ENABLED=true but PUBLIC/SECRET keys missing; "
            "tracing disabled"
        )
        _client = None
        return None

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("langfuse: initialized client host=%s", settings.langfuse_host)
    except Exception as exc:  # noqa: BLE001
        # Per design Decision 7 + Risks table: trace infra must never block main path.
        logger.warning("langfuse: init failed (%s); tracing disabled", exc)
        _client = None

    return _client


def get_client() -> Any | None:
    """Return the cached client, lazy-initializing on first call."""
    if not _initialized:
        return init_langfuse()
    return _client


def observe(*decorator_args: Any, **decorator_kwargs: Any) -> Callable[[_F], _F]:
    """Re-export of langfuse `@observe` decorator with no-op fallback.

    When tracing is disabled or langfuse is not installed, the decorator
    is a pass-through that returns the wrapped function unchanged.
    """
    # Determine whether the real langfuse decorator should be used.
    if not settings.eval_tracing_enabled:
        return _noop_decorator

    try:
        from langfuse import observe as _real_observe
    except ImportError:
        logger.debug("langfuse: package not installed, observe() is a no-op")
        return _noop_decorator

    return _real_observe(*decorator_args, **decorator_kwargs)


def _noop_decorator(func: _F) -> _F:
    """Identity decorator used when tracing is disabled."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
