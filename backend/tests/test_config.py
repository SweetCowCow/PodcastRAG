"""Settings validators."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _base_env() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql+asyncpg://x:y@localhost/z",
        "FRONTEND_ORIGIN": "http://localhost:8080",
        "SESSION_SECRET": "x" * 32,
        "GOOGLE_CLIENT_ID": "x",
        "GOOGLE_CLIENT_SECRET": "x",
        "GOOGLE_REDIRECT_URI": "http://localhost",
    }


def test_e2e_login_token_none(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("E2E_LOGIN_TOKEN", raising=False)
    s = Settings()
    assert s.e2e_login_token is None


def test_e2e_login_token_too_short(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("E2E_LOGIN_TOKEN", "short")
    with pytest.raises(ValidationError):
        Settings()


def test_e2e_login_token_valid(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    token = "a" * 64
    monkeypatch.setenv("E2E_LOGIN_TOKEN", token)
    s = Settings()
    assert s.e2e_login_token == token


def test_e2e_login_token_empty_string_treated_as_none(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("E2E_LOGIN_TOKEN", "")
    s = Settings()
    assert s.e2e_login_token is None
