import asyncio

import httpx
import openai
import pytest

from app.services.api_health import classify_error


def _make_openai_status_exc(cls, status_code: int, body: dict | None = None):
    request = httpx.Request("POST", "https://api.openai.com/v1/x")
    response = httpx.Response(status_code, request=request, json=body or {})
    return cls(message="x", response=response, body=body)


def test_classify_quota_exceeded():
    exc = _make_openai_status_exc(
        openai.RateLimitError,
        429,
        {"error": {"code": "insufficient_quota", "message": "out of quota"}},
    )
    assert classify_error(exc, 429) == "quota_exceeded"


def test_classify_rate_limited():
    exc = _make_openai_status_exc(
        openai.RateLimitError,
        429,
        {"error": {"code": "rate_limit_exceeded", "message": "slow down"}},
    )
    assert classify_error(exc, 429) == "rate_limited"


def test_classify_auth_error():
    exc = _make_openai_status_exc(
        openai.AuthenticationError,
        401,
        {"error": {"code": "invalid_api_key", "message": "bad key"}},
    )
    assert classify_error(exc, 401) == "auth_error"


def test_classify_server_error_from_http_status():
    assert classify_error(None, 503) == "server_error"


def test_classify_network_error():
    exc = httpx.ConnectError("connection refused")
    assert classify_error(exc, None) == "network_error"


def test_classify_unknown():
    assert classify_error(ValueError("bad input"), None) == "unknown"


def test_classify_asyncio_timeout_is_network():
    assert classify_error(asyncio.TimeoutError(), None) == "network_error"
