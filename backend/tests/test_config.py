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


def test_summary_stale_threshold_default(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SUMMARY_STALE_THRESHOLD_SECONDS", raising=False)
    s = Settings()
    assert s.summary_stale_threshold_seconds == 600


def test_summary_stale_threshold_env_override(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SUMMARY_STALE_THRESHOLD_SECONDS", "120")
    s = Settings()
    assert s.summary_stale_threshold_seconds == 120


def test_default_user_quota_default(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("DEFAULT_USER_QUOTA", raising=False)
    s = Settings()
    assert s.default_user_quota == 30


def test_default_user_quota_env_override(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DEFAULT_USER_QUOTA", "50")
    s = Settings()
    assert s.default_user_quota == 50


def test_ip_search_rate_limit_default(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("IP_SEARCH_RATE_LIMIT_PER_DAY", raising=False)
    s = Settings()
    assert s.ip_search_rate_limit_per_day == 20


def test_ip_search_rate_limit_env_override(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("IP_SEARCH_RATE_LIMIT_PER_DAY", "5")
    s = Settings()
    assert s.ip_search_rate_limit_per_day == 5


def test_zsend_settings_default_to_none(monkeypatch):
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    for k in ("ZSEND_API_KEY", "ZSEND_FROM_EMAIL", "ZSEND_ADMIN_TO_EMAIL"):
        monkeypatch.delenv(k, raising=False)
    s = Settings()
    assert s.zsend_api_key is None
    assert s.zsend_from_email is None
    assert s.zsend_admin_to_email is None
