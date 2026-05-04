"""Unit tests for app.services.zsend.send_email."""
import httpx
import pytest

from app.services import zsend


@pytest.fixture(autouse=True)
def _zsend_env(monkeypatch):
    monkeypatch.setattr(zsend.settings, "zsend_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        zsend.settings, "zsend_from_email", "noreply@test.local", raising=False
    )


@pytest.mark.asyncio
async def test_send_email_success(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = request.read().decode()
        return httpx.Response(200, json={"id": "msg-1"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class _PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zsend.httpx, "AsyncClient", _PatchedClient)

    await zsend.send_email("admin@test.local", "S", "B")

    assert captured["url"].endswith("/api/v1/send")
    assert "Bearer test-key" in captured["headers"].get("authorization", "")
    assert "noreply@test.local" in captured["json"]
    assert "admin@test.local" in captured["json"]


@pytest.mark.asyncio
async def test_send_email_missing_api_key_raises_non_retryable(monkeypatch):
    monkeypatch.setattr(zsend.settings, "zsend_api_key", None, raising=False)
    with pytest.raises(zsend.ZSendError) as exc_info:
        await zsend.send_email("a@b.c", "s", "b")
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_send_email_5xx_retryable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class _PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zsend.httpx, "AsyncClient", _PatchedClient)

    with pytest.raises(zsend.ZSendError) as exc_info:
        await zsend.send_email("a@b.c", "s", "b")
    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_send_email_4xx_not_retryable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "bad email format"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class _PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zsend.httpx, "AsyncClient", _PatchedClient)

    with pytest.raises(zsend.ZSendError) as exc_info:
        await zsend.send_email("bad", "s", "b")
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_send_email_network_error_retryable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failed")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class _PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zsend.httpx, "AsyncClient", _PatchedClient)

    with pytest.raises(zsend.ZSendError) as exc_info:
        await zsend.send_email("a@b.c", "s", "b")
    assert exc_info.value.retryable is True
