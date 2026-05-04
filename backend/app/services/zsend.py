"""ZSend (Zeabur Email) HTTP client.

Used by the quota_digest beat task. When `settings.zsend_api_key` is unset,
callers should skip invoking these helpers; this module does not auto-skip
(callers are responsible for the no-op check) so that misconfiguration is
explicit at the call site.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Per Zeabur Email (ZSend) docs the send endpoint lives at this URL.
ZSEND_BASE_URL = "https://api.zeabur.com"
ZSEND_SEND_PATH = "/api/v1/zsend/emails"

DEFAULT_TIMEOUT_SECONDS = 30.0


class ZSendError(Exception):
    """ZSend client error. ``retryable`` indicates whether the caller's
    retry policy (e.g. Celery autoretry_for) should treat this as transient.
    Network errors and 5xx are retryable; 4xx are not."""

    def __init__(self, message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


async def send_email(to: str, subject: str, body_text: str) -> None:
    """Send a plain-text email via ZSend. Raises ZSendError on failure.

    The caller MUST ensure ``settings.zsend_api_key`` and ``zsend_from_email``
    are configured. Validation is done here (raise if missing) so the failure
    mode is explicit, but production callers should pre-check to avoid the
    extra HTTP attempt.
    """
    if not settings.zsend_api_key:
        raise ZSendError("ZSEND_API_KEY is not configured", retryable=False)
    if not settings.zsend_from_email:
        raise ZSendError("ZSEND_FROM_EMAIL is not configured", retryable=False)

    payload = {
        "from": settings.zsend_from_email,
        "to": [to],  # ZSend expects an array of recipients
        "subject": subject,
        "text": body_text,
    }
    headers = {
        "Authorization": f"Bearer {settings.zsend_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{ZSEND_BASE_URL}{ZSEND_SEND_PATH}"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        # Network-level failures: connect refused, DNS, timeout. Retryable.
        raise ZSendError(
            f"ZSend request failed: {exc!r}", retryable=True
        ) from exc

    if 200 <= resp.status_code < 300:
        return

    # Non-2xx. Distinguish 4xx (client error, do not retry) from 5xx (retry).
    detail = resp.text[:500]
    retryable = resp.status_code >= 500
    logger.warning(
        "zsend send_email non-2xx: status=%s body=%s", resp.status_code, detail
    )
    raise ZSendError(
        f"ZSend HTTP {resp.status_code}: {detail}",
        retryable=retryable,
        status_code=resp.status_code,
    )
