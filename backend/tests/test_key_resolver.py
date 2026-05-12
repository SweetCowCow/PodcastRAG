"""Tests for services.key_resolver.

Covers design D7: env > cache > DB > KeyError, plus caplog assertion that the
resolver never logs a key value in any path.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.api_key import ApiKey
from app.services import key_resolver
from app.services.key_resolver import get_provider_key


def _db_reachable() -> bool:
    """Probe the configured DATABASE_URL host/port instead of hard-coding
    127.0.0.1, so the same suite passes both on host (local PG) and inside
    the backend container (db service)."""
    import socket
    from urllib.parse import urlparse

    from app.core.config import settings

    # Normalise SQLAlchemy URL → urllib-parseable.
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


db_required = pytest.mark.skipif(
    not _db_reachable(), reason="configured postgres not reachable"
)


# Test label prefix lets us safely DELETE only our own rows on cleanup.
_TEST_LABEL_PREFIX = "pytest-keyresolver-"
_TEST_PROVIDER_PREFIX = "pytest-keyresolver"


@pytest_asyncio.fixture
async def clean_api_keys(db_session):
    """Remove any leftover pytest-keyresolver rows before & after each test."""
    key_resolver._reset_cache_for_tests()
    await db_session.execute(
        delete(ApiKey).where(ApiKey.label.like(f"{_TEST_LABEL_PREFIX}%"))
    )
    await db_session.commit()
    yield db_session
    key_resolver._reset_cache_for_tests()
    await db_session.execute(
        delete(ApiKey).where(ApiKey.label.like(f"{_TEST_LABEL_PREFIX}%"))
    )
    await db_session.commit()


async def _seed_key(db, provider: str, api_key: str, *, created_at=None):
    suffix = uuid.uuid4().hex[:8]
    row = ApiKey(
        provider=provider,
        label=f"{_TEST_LABEL_PREFIX}{suffix}",
        api_key=api_key,
    )
    if created_at is not None:
        row.created_at = created_at
        row.updated_at = created_at
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@db_required
@pytest.mark.asyncio
async def test_prefer_env_set_returns_env_value(monkeypatch, clean_api_keys):
    """env override beats DB and skips the query entirely."""
    monkeypatch.setenv("OPENAI_OFFICIAL_KEY", "sk-test-env")
    # Seed a DB row that should be ignored.
    await _seed_key(clean_api_keys, f"{_TEST_PROVIDER_PREFIX}-env", "sk-test-db-ignored")

    # Patch the DB resolver to raise — if it gets called, test fails loudly.
    called = {"n": 0}

    async def _boom(_provider):
        called["n"] += 1
        raise AssertionError("_resolve_from_db should not be called when env is set")

    monkeypatch.setattr(key_resolver, "_resolve_from_db", _boom)

    value = get_provider_key(
        f"{_TEST_PROVIDER_PREFIX}-env", prefer_env="OPENAI_OFFICIAL_KEY"
    )
    assert value == "sk-test-env"
    assert called["n"] == 0


@db_required
@pytest.mark.asyncio
async def test_prefer_env_empty_falls_back_to_db(monkeypatch, clean_api_keys):
    """Empty/missing env var → fall through to DB."""
    monkeypatch.setenv("OPENAI_OFFICIAL_KEY", "")
    provider = f"{_TEST_PROVIDER_PREFIX}-fallback"
    await _seed_key(clean_api_keys, provider, "sk-test-db")

    value = get_provider_key(provider, prefer_env="OPENAI_OFFICIAL_KEY")
    assert value == "sk-test-db"


@db_required
@pytest.mark.asyncio
async def test_db_multiple_rows_returns_latest(clean_api_keys):
    """Multiple rows for the same provider → ORDER BY created_at DESC LIMIT 1."""
    provider = f"{_TEST_PROVIDER_PREFIX}-multi"
    now = datetime.now(timezone.utc)
    await _seed_key(
        clean_api_keys, provider, "sk-test-older", created_at=now - timedelta(seconds=5)
    )
    await _seed_key(clean_api_keys, provider, "sk-test-newer", created_at=now)

    value = get_provider_key(provider)
    assert value == "sk-test-newer"


@db_required
@pytest.mark.asyncio
async def test_db_miss_raises_key_error(clean_api_keys):
    """Provider with no row → KeyError naming the provider, no key value."""
    provider = f"{_TEST_PROVIDER_PREFIX}-nonexistent"
    with pytest.raises(KeyError, match=r"provider='pytest-keyresolver-nonexistent'"):
        get_provider_key(provider)


@db_required
@pytest.mark.asyncio
async def test_no_key_logged(monkeypatch, caplog, clean_api_keys):
    """Across success + miss paths, no log record contains any key value."""
    monkeypatch.setenv("OPENAI_OFFICIAL_KEY", "sk-test-env-secret")
    provider_hit = f"{_TEST_PROVIDER_PREFIX}-loghit"
    provider_miss = f"{_TEST_PROVIDER_PREFIX}-logmiss"
    await _seed_key(clean_api_keys, provider_hit, "sk-test-db-secret")

    caplog.set_level(logging.DEBUG)

    # Path 1: env hit.
    assert (
        get_provider_key(provider_hit, prefer_env="OPENAI_OFFICIAL_KEY")
        == "sk-test-env-secret"
    )

    # Path 2: clear env so DB path fires, cache hit on 3rd call.
    monkeypatch.delenv("OPENAI_OFFICIAL_KEY", raising=False)
    key_resolver._reset_cache_for_tests()
    assert get_provider_key(provider_hit) == "sk-test-db-secret"
    assert get_provider_key(provider_hit) == "sk-test-db-secret"  # cache hit

    # Path 3: miss.
    with pytest.raises(KeyError):
        get_provider_key(provider_miss)

    forbidden = ("sk-test-env-secret", "sk-test-db-secret", "sk-")
    for record in caplog.records:
        msg = record.getMessage()
        for needle in forbidden:
            assert needle not in msg, (
                f"Resolver leaked key-shaped string {needle!r} via "
                f"logger={record.name} level={record.levelname}"
            )


@db_required
@pytest.mark.asyncio
async def test_cache_hit_skips_db(monkeypatch, clean_api_keys):
    """Two consecutive calls with same args → DB query called exactly once."""
    provider = f"{_TEST_PROVIDER_PREFIX}-cache"
    await _seed_key(clean_api_keys, provider, "sk-test-cache")

    real_resolve = key_resolver._resolve_from_db
    call_count = {"n": 0}

    async def _counting(prov):
        call_count["n"] += 1
        return await real_resolve(prov)

    monkeypatch.setattr(key_resolver, "_resolve_from_db", _counting)

    a = get_provider_key(provider)
    b = get_provider_key(provider)
    assert a == b == "sk-test-cache"
    assert call_count["n"] == 1
