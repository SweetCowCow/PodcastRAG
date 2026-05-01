"""Tests for unified error response schema and global exception handler.

Tests that don't require a database run unconditionally. Integration tests that
need DB / external services are marked with `db_required` and skip cleanly when
no local postgres is reachable. Prod chrome-devtools-mcp validation covers the
DB-required paths end-to-end (path A pattern).
"""

import socket
from unittest.mock import patch

import openai
import pytest
import pytest_asyncio
from fastapi import APIRouter, HTTPException
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.errors import ErrorCode


def _postgres_reachable() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    try:
        sock.connect(("127.0.0.1", 5432))
        return True
    except OSError:
        return False
    finally:
        sock.close()


db_required = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="local postgres not running; prod validation covers this path",
)


# Register dev-only test endpoints once for the global-handler suite.
_test_router = APIRouter()


@_test_router.get("/_test/raise-runtime")
async def _raise_runtime():
    raise RuntimeError("simulated unhandled error")


@_test_router.get("/_test/raise-http-404")
async def _raise_http_404():
    raise HTTPException(status_code=404, detail="resource not found")


if not any(
    getattr(r, "path", None) == "/_test/raise-runtime" for r in app.routes
):
    app.include_router(_test_router)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:8080"},
    ) as ac:
        yield ac


# ---------- 5.1 (a): global handler 兜底 + CORS ----------


async def test_unhandled_exception_returns_internal_error_with_cors(client):
    res = await client.get("/_test/raise-runtime")
    assert res.status_code == 500
    body = res.json()
    assert body["detail"]["error_code"] == ErrorCode.INTERNAL_ERROR
    assert body["detail"]["provider"] is None
    # CORS header MUST be present so the browser can read the body
    assert "access-control-allow-origin" in {k.lower() for k in res.headers.keys()}


# ---------- 5.1 (b): HTTPException 不被 global handler 攔截 ----------


async def test_http_exception_keeps_string_detail(client):
    res = await client.get("/_test/raise-http-404")
    assert res.status_code == 404
    body = res.json()
    # Legacy shape: detail is a plain string, not the new ErrorResponse dict
    assert body["detail"] == "resource not found"


# ---------- 5.1 (c): RequestValidationError 仍走 FastAPI default 422 ----------


async def test_pydantic_validation_error_returns_422(client):
    # POST /shows requires a body; sending empty triggers Pydantic 422
    res = await client.post("/shows", json={})
    assert res.status_code == 422
    body = res.json()
    # FastAPI's default 422 shape: detail is a list of validation errors
    assert isinstance(body["detail"], list)


# ---------- 5.6: ErrorCode 常數 (Risk 4 mitigation) ----------


def test_error_code_constants_present():
    """All error_code strings raised in app/api/* must exist as ErrorCode constants."""
    expected = {
        "llm_quota_exceeded",
        "llm_rate_limited",
        "llm_auth_failed",
        "llm_unavailable",
        "llm_not_configured",
        "rss_timeout",
        "rss_invalid",
        "show_duplicate_rss",
        "internal_error",
    }
    actual = {
        getattr(ErrorCode, name)
        for name in dir(ErrorCode)
        if not name.startswith("_") and isinstance(getattr(ErrorCode, name), str)
    }
    assert expected.issubset(actual), f"missing: {expected - actual}"


# ---------- 5.2 / 5.3 / 5.5: query endpoint OpenAI 例外整合測試 (needs DB) ----------


@db_required
async def test_query_rate_limit_insufficient_quota_returns_429(client):
    """When embed_texts raises RateLimitError(insufficient_quota), endpoint returns 429 + llm_quota_exceeded."""
    import uuid as _uuid

    from app.core.database import AsyncSessionFactory
    from app.models.show import Show

    async with AsyncSessionFactory() as db:
        show = Show(
            title="Err Test",
            rss_url=f"https://example.com/rss/{_uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()
        show_id = show.id
        await db.commit()

    try:
        rate_limit_exc = openai.RateLimitError(
            message="quota exceeded",
            response=_FakeResponse(429),
            body={"error": {"code": "insufficient_quota"}},
        )
        with patch("app.api.query.embed_texts", side_effect=rate_limit_exc):
            res = await client.post(
                f"/shows/{show_id}/query",
                json={"question": "hi", "mode": "search", "messages": []},
            )
        assert res.status_code == 429
        body = res.json()["detail"]
        assert body["error_code"] == ErrorCode.LLM_QUOTA_EXCEEDED
        assert body["provider"] == "OpenAI"
    finally:
        async with AsyncSessionFactory() as db:
            await db.execute(
                __import__("sqlalchemy").delete(Show).where(Show.id == show_id)
            )
            await db.commit()


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.headers = {}
        self.request = None


def _make_rate_limit_exc(insufficient_quota: bool = False) -> openai.RateLimitError:
    body = {"error": {"code": "insufficient_quota"}} if insufficient_quota else {"error": {"code": "rate_limit"}}
    return openai.RateLimitError(
        message="rate limited", response=_FakeResponse(429), body=body
    )


def _make_auth_exc() -> openai.AuthenticationError:
    return openai.AuthenticationError(
        message="bad key", response=_FakeResponse(401), body={"error": {"code": "invalid_api_key"}}
    )


def _make_connection_exc() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=None)


def _make_timeout_exc() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=None)


@pytest_asyncio.fixture
async def show_id_for_query():
    """Create a temp Show row for query endpoint tests; cleanup after."""
    import uuid as _uuid

    import sqlalchemy as _sa

    from app.core.database import AsyncSessionFactory
    from app.models.show import Show

    async with AsyncSessionFactory() as db:
        show = Show(
            title="Err Test",
            rss_url=f"https://example.com/rss/{_uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()
        sid = show.id
        await db.commit()
    try:
        yield sid
    finally:
        async with AsyncSessionFactory() as db:
            await db.execute(_sa.delete(Show).where(Show.id == sid))
            await db.commit()


# ---------- 5.2: 五種 OpenAI 例外 → 對應 status code + error_code + provider=OpenAI ----------


@db_required
@pytest.mark.parametrize(
    "make_exc, expected_status, expected_code",
    [
        (lambda: _make_rate_limit_exc(insufficient_quota=True), 429, ErrorCode.LLM_QUOTA_EXCEEDED),
        (lambda: _make_rate_limit_exc(insufficient_quota=False), 429, ErrorCode.LLM_RATE_LIMITED),
        (_make_auth_exc, 502, ErrorCode.LLM_AUTH_FAILED),
        (_make_connection_exc, 503, ErrorCode.LLM_UNAVAILABLE),
        (_make_timeout_exc, 503, ErrorCode.LLM_UNAVAILABLE),
    ],
)
async def test_query_search_openai_exception_mapping(
    client, show_id_for_query, make_exc, expected_status, expected_code
):
    with patch("app.api.query.embed_texts", side_effect=make_exc()):
        res = await client.post(
            f"/shows/{show_id_for_query}/query",
            json={"question": "hi", "mode": "search", "messages": []},
        )
    assert res.status_code == expected_status
    body = res.json()["detail"]
    assert body["error_code"] == expected_code
    assert body["provider"] == "OpenAI"


# ---------- 5.3: chat 路徑 RateLimit 且 base_url 含 zeabur → provider="Zeabur AI Hub" ----------


@db_required
async def test_query_chat_zeabur_provider_label(client, show_id_for_query):
    """When chat answer model raises RateLimitError and answer_base_url is Zeabur,
    provider label MUST be "Zeabur AI Hub"."""
    from app.core.database import AsyncSessionFactory
    from app.services.llm_config import get_config

    async with AsyncSessionFactory() as db:
        cfg = await get_config(db)
        original = (cfg.answer_base_url, cfg.answer_api_key, cfg.rewrite_api_key)
        cfg.answer_base_url = "https://aihub-test.zeabur.app/v1"
        cfg.answer_api_key = "sk-test"
        cfg.rewrite_api_key = "sk-test"
        await db.commit()

    try:
        # mock so embed succeeds, retrieve returns [], answer raises RateLimitError
        with patch("app.api.query.embed_texts", return_value=[[0.0] * 1536]), patch(
            "app.api.query.rag.retrieve", return_value=[]
        ), patch(
            "app.api.query.rag.answer_with_chunks",
            side_effect=_make_rate_limit_exc(insufficient_quota=False),
        ):
            res = await client.post(
                f"/shows/{show_id_for_query}/query",
                json={"question": "hi", "mode": "chat", "messages": []},
            )
        assert res.status_code == 429
        body = res.json()["detail"]
        assert body["provider"] == "Zeabur AI Hub"
        assert body["error_code"] == ErrorCode.LLM_RATE_LIMITED
    finally:
        async with AsyncSessionFactory() as db:
            cfg = await get_config(db)
            cfg.answer_base_url, cfg.answer_api_key, cfg.rewrite_api_key = original
            await db.commit()


# ---------- 5.4: RSS 例外 case ----------


@db_required
async def test_create_show_rss_invalid_returns_422(client):
    from app.services.rss_parser import RssParseError

    with patch(
        "app.api.shows.fetch_and_parse",
        side_effect=RssParseError("not a valid RSS"),
    ):
        res = await client.post("/shows", json={"rss_url": "https://example.com/bad"})
    assert res.status_code == 422
    body = res.json()["detail"]
    assert body["error_code"] == ErrorCode.RSS_INVALID


@db_required
async def test_create_show_rss_timeout_returns_504(client):
    import httpx as _httpx

    with patch(
        "app.api.shows.fetch_and_parse",
        side_effect=_httpx.TimeoutException("timeout"),
    ):
        res = await client.post(
            "/shows", json={"rss_url": "https://example.com/timeout"}
        )
    assert res.status_code == 504
    body = res.json()["detail"]
    assert body["error_code"] == ErrorCode.RSS_TIMEOUT


# ---------- 5.5: embedding.py 既有 retry 不被破壞 ----------


@db_required
async def test_embedding_retry_succeeds_endpoint_returns_200(client, show_id_for_query):
    """First call raises RateLimitError, second succeeds — embedding.py internal
    retry MUST swallow the error and the endpoint MUST return 200."""
    from app.services import embedding as _embed_mod

    call_count = {"n": 0}
    real_create = None

    class _FakeEmbeddings:
        def create(self, model, input):  # noqa: A002 — match OpenAI SDK signature
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _make_rate_limit_exc(insufficient_quota=False)

            class _Item:
                embedding = [0.0] * 1536

            class _Resp:
                data = [_Item() for _ in input]

            return _Resp()

    class _FakeClient:
        embeddings = _FakeEmbeddings()

    with patch.object(
        _embed_mod, "OpenAI", return_value=_FakeClient()
    ), patch("app.api.query.rag.retrieve", return_value=[]):
        res = await client.post(
            f"/shows/{show_id_for_query}/query",
            json={"question": "hi", "mode": "search", "messages": []},
        )
    assert res.status_code == 200
    assert call_count["n"] >= 2  # retried at least once
