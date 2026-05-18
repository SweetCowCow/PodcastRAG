"""task-failure-monitoring-and-circuit-breaker: error_classifier coverage.

Test cases come straight from the spec's example table (10 rows). No
database / network dependencies — pure unit tests.
"""
from __future__ import annotations

import httpx
import pytest

from app.services.error_classifier import classify
from app.services.exceptions import (
    InvalidProviderConfigError,
    PromptTooLongError,
)


def _http_status_error(status_code: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/api")
    response = httpx.Response(status_code=status_code, text=body, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}", request=request, response=response
    )


@pytest.mark.parametrize(
    "exc, expected",
    [
        # 1. HTTP 401 → permanent (invalid_api_key)
        (_http_status_error(401), "permanent"),
        # 2. HTTP 402 → permanent (payment required)
        (_http_status_error(402), "permanent"),
        # 3. HTTP 415 → permanent (unsupported media)
        (_http_status_error(415), "permanent"),
        # 4. HTTP 400 with permanent body → permanent
        (
            _http_status_error(400, body="context_length_exceeded for model"),
            "permanent",
        ),
        # 5. HTTP 400 plain → transient (保守：未知 400 不誤殺)
        (_http_status_error(400, body="bad request"), "transient"),
        # 6. HTTP 429 → transient (rate limit, retry helps)
        (_http_status_error(429), "transient"),
        # 7. HTTP 503 → transient (transient backend hiccup)
        (_http_status_error(503), "transient"),
        # 8. httpx.TimeoutException → transient
        (httpx.TimeoutException("read timeout"), "transient"),
    ],
)
def test_classify_http_and_timeout(exc, expected):
    assert classify(exc) == expected


def test_celery_not_registered_is_permanent():
    """Spec example 9: TaskNotRegistered classified permanent.

    Imported lazily so the test still runs when celery is not installed
    in the host env (it always is in CI / backend, so this is just defence).
    """
    from celery.exceptions import NotRegistered

    assert classify(NotRegistered("app.workers.foo")) == "permanent"


def test_unknown_keyerror_is_treated_as_transient():
    """Spec example 10: ``KeyError("missing")`` → caller treats as transient.

    Our classifier currently returns ``'transient'`` for plain KeyError
    because it has no http status / known permanent ancestor. The spec
    accepts either ``'unknown'`` or ``'transient'`` as long as the retry
    path is taken — ``'transient'`` is the stricter choice (always retry).
    """
    result = classify(KeyError("missing"))
    assert result in {"transient", "unknown"}


def test_custom_invalid_provider_config_is_permanent():
    assert classify(InvalidProviderConfigError("base_url missing")) == "permanent"


def test_custom_prompt_too_long_is_permanent():
    assert classify(PromptTooLongError("prompt has 200k tokens")) == "permanent"


def test_classifier_never_raises_on_weird_exception():
    """Defensive: even if exc shape is bizarre, classifier returns a value."""

    class Weird(Exception):
        @property
        def status_code(self):  # raises when accessed
            raise RuntimeError("boom")

    # Should NOT raise; falls back to transient/unknown.
    result = classify(Weird())
    assert result in {"transient", "unknown"}
