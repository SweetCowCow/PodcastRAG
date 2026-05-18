"""Classify Celery task exceptions as permanent / transient / unknown.

Part of `task-failure-monitoring-and-circuit-breaker`. Used by:

- ``failure_log.write_failure_log`` to set ``failure_type``
- Worker task error-handling paths to decide whether to short-circuit
  Celery's ``autoretry_for`` (permanent → re-raise without retry).

The whitelist policy is "permanent only":

- HTTP 401 / 402 / 403 / 415 / 422 → permanent
- HTTP 400 with body matching known permanent patterns → permanent
  (``context_length_exceeded`` / ``invalid_api_key`` / ``insufficient_quota``)
- Celery ``NotRegistered`` / kombu ``MessageStateError`` → permanent
- Custom ``InvalidProviderConfigError`` / ``PromptTooLongError`` → permanent

Everything else → transient. Truly unrecognised exception shapes (no
status_code / unknown class) → unknown (treated as transient for retry
purposes, but stored in ``task_failure_log.failure_type='unknown'`` so
ops can audit later).

Conservative on purpose: better to retry a real permanent error (wasted
quota) than to mark a transient error permanent (silently giving up).
"""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)


# HTTP statuses that are always permanent for our external providers.
# - 401: invalid_api_key
# - 402: payment required / insufficient quota (some providers)
# - 403: forbidden (no permission / disabled account)
# - 415: unsupported media (Whisper >25MiB also fits via 413, kept here as
#        documented permanent failure type)
# - 422: unprocessable entity (validation failure)
_PERMANENT_HTTP_STATUS: frozenset[int] = frozenset({401, 402, 403, 415, 422})

# When HTTP 400 is hit, the body often distinguishes permanent (prompt too
# long, bad api key forwarded by gateway) from transient (malformed
# transient input). Match these substrings case-insensitively in the body.
_HTTP_400_PERMANENT_PATTERNS: tuple[str, ...] = (
    "context_length_exceeded",
    "invalid_api_key",
    "insufficient_quota",
)

# Classes whose mere presence indicates permanent failure (full dotted
# name; we walk MRO to handle subclasses).
_PERMANENT_CLASS_FULL_NAMES: frozenset[str] = frozenset(
    {
        "celery.exceptions.NotRegistered",
        "kombu.exceptions.MessageStateError",
        "app.services.exceptions.InvalidProviderConfigError",
        "app.services.exceptions.PromptTooLongError",
        # Existing project exceptions that are inherently permanent.
        "app.services.exceptions.OversizedAudioError",
    }
)


ClassifyResult = Literal["permanent", "transient", "unknown"]


def _full_class_name(cls: type) -> str:
    module = getattr(cls, "__module__", "") or ""
    name = getattr(cls, "__qualname__", cls.__name__)
    return f"{module}.{name}" if module else name


def _has_permanent_ancestor(exc: BaseException) -> bool:
    for cls in type(exc).__mro__:
        if _full_class_name(cls) in _PERMANENT_CLASS_FULL_NAMES:
            return True
    return False


def _http_status_of(exc: BaseException) -> int | None:
    """Best-effort extraction of HTTP status from common SDK exception shapes.

    Handles:
    - ``httpx.HTTPStatusError`` (``.response.status_code``)
    - ``openai`` SDK errors (``.status_code``)
    - generic exceptions with ``.status_code`` / ``.response.status_code``
    """
    sc = getattr(exc, "status_code", None)
    if isinstance(sc, int):
        return sc
    resp = getattr(exc, "response", None)
    if resp is not None:
        sc = getattr(resp, "status_code", None)
        if isinstance(sc, int):
            return sc
    return None


def _http_body_of(exc: BaseException) -> str:
    """Best-effort extraction of response body text for pattern matching."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        text = getattr(resp, "text", None)
        if isinstance(text, str):
            return text
    # Fall back to the exception's string form which often embeds the body.
    return str(exc) or ""


def classify(exc: BaseException) -> ClassifyResult:
    """Return ``'permanent' | 'transient' | 'unknown'`` for ``exc``.

    ``'unknown'`` only fires when we genuinely cannot inspect the shape.
    Callers should treat ``'unknown'`` the same as ``'transient'`` for
    retry purposes but persist the original verdict in the failure log.
    """
    try:
        if _has_permanent_ancestor(exc):
            return "permanent"

        status = _http_status_of(exc)
        if status is not None:
            if status in _PERMANENT_HTTP_STATUS:
                return "permanent"
            if status == 400:
                body = _http_body_of(exc).lower()
                if any(p in body for p in _HTTP_400_PERMANENT_PATTERNS):
                    return "permanent"
                return "transient"
            # All other HTTP statuses (incl. 429 / 5xx) → transient.
            return "transient"

        # Known transient exception types (timeouts / connection issues)
        # don't need a positive match because the default is transient;
        # listing them here is documentation only.
        return "transient"
    except Exception:  # defensive: never let classifier crash a worker
        logger.exception(
            "error_classifier: classify(%r) raised — returning unknown",
            type(exc).__name__,
        )
        return "unknown"
