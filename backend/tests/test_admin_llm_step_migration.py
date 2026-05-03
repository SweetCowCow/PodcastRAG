"""Migration tests for admin-llm-step-config Rev A and Rev B.

These tests spin up a *separate* postgres database per test, run alembic
against it via subprocess, and inspect the resulting schema/data. Slower
than other tests but isolates DDL from the main test DB.
"""
from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)

REV_A = "l0a1b2c3d4e5"
REV_B = "m1b2c3d4e5f6"

ADMIN_URL_ASYNC = "postgresql+asyncpg://postgres:password@localhost:5432/postgres"
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _sync_dsn(db_name: str) -> str:
    return f"postgresql+psycopg2://postgres:password@localhost:5432/{db_name}"


def _async_dsn(db_name: str) -> str:
    return f"postgresql+asyncpg://postgres:password@localhost:5432/{db_name}"


def _alembic_upgrade(db_name: str, target: str, *, openai_api_key: str = "") -> None:
    env = os.environ.copy()
    # Alembic env.py reads settings.database_url, which uses asyncpg dialect.
    env["DATABASE_URL"] = _async_dsn(db_name)
    env["FRONTEND_ORIGIN"] = "http://localhost:8080"
    env["OPENAI_API_KEY"] = openai_api_key
    env.setdefault("SESSION_SECRET", "test-session-secret-thirtytwo+chars-padding")
    env.setdefault("GOOGLE_CLIENT_ID", "x")
    env.setdefault("GOOGLE_CLIENT_SECRET", "x")
    env.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    env.setdefault("ADMIN_EMAILS", "")
    env.setdefault("TRANSCRIPTION_PROVIDER", "openai")
    result = subprocess.run(
        ["python", "-m", "alembic", "upgrade", target],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade {target} failed:\nSTDOUT:{result.stdout}\nSTDERR:{result.stderr}"
        )


@pytest_asyncio.fixture
async def temp_db():
    """Create + drop a unique postgres database per test."""
    db_name = f"test_admin_llm_{secrets.token_hex(6)}"
    admin_engine = create_async_engine(ADMIN_URL_ASYNC, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    # pgvector extension is required by some pre-existing migrations
    eng = create_async_engine(_async_dsn(db_name))
    async with eng.connect() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.commit()
    await eng.dispose()
    yield db_name
    async with admin_engine.connect() as conn:
        # Force-drop any open backends
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ),
            {"db": db_name},
        )
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    await admin_engine.dispose()


async def _scalar(db_name: str, sql: str) -> object:
    eng = create_async_engine(_async_dsn(db_name))
    async with eng.connect() as conn:
        result = await conn.execute(text(sql))
        row = result.first()
        await conn.close()
    await eng.dispose()
    return row[0] if row else None


async def _all(db_name: str, sql: str) -> list[tuple]:
    eng = create_async_engine(_async_dsn(db_name))
    async with eng.connect() as conn:
        result = await conn.execute(text(sql))
        rows = list(result.all())
        await conn.close()
    await eng.dispose()
    return rows


@db_required
@pytest.mark.asyncio
async def test_rev_a_clean_db_creates_five_steps(temp_db):
    """Task 8.1 — fresh DB: 5 step rows, llm_config still exists, OPENAI key imported."""
    _alembic_upgrade(temp_db, REV_A, openai_api_key="sk-test-clean-db")

    step_keys = await _all(temp_db, "SELECT step_key FROM ai_steps ORDER BY step_key")
    assert [r[0] for r in step_keys] == [
        "answer", "embedding", "rewrite", "summary", "transcription",
    ]

    # llm_config table SHALL still exist after Rev A (Rev B drops it later).
    llm_config_exists = await _scalar(
        temp_db,
        "SELECT to_regclass('llm_config') IS NOT NULL",
    )
    assert llm_config_exists is True

    # api_keys must include the legacy-env-import OpenAI key.
    keys = await _all(
        temp_db,
        "SELECT provider, label, api_key FROM api_keys ORDER BY label",
    )
    assert any(
        p == "openai" and lab == "legacy-env-import" and k == "sk-test-clean-db"
        for (p, lab, k) in keys
    ), f"expected OpenAI legacy-env-import row, got {keys}"


@db_required
@pytest.mark.asyncio
async def test_rev_a_imports_legacy_llm_config(temp_db):
    """Task 8.2 — pre-seed llm_config + env, run Rev A, verify import."""
    # Bring DB up to revision just before our Rev A so llm_config exists.
    _alembic_upgrade(temp_db, "k9f0a1b2c3d4")

    # Seed the legacy llm_config row as if a user had configured Hub.
    eng = create_async_engine(_async_dsn(temp_db))
    async with eng.connect() as conn:
        # Earlier migration seeds id=1 with empty values; UPSERT to set our values.
        await conn.execute(
            text(
                "INSERT INTO llm_config (id, answer_base_url, answer_api_key, answer_model, "
                "rewrite_base_url, rewrite_api_key, rewrite_model) VALUES "
                "(1, 'https://hnd1.aihub.zeabur.ai/v1', 'K_HUB', 'gpt-4o', "
                "'https://hnd1.aihub.zeabur.ai/v1', 'K_HUB', 'gpt-4o-mini') "
                "ON CONFLICT (id) DO UPDATE SET "
                "answer_base_url=EXCLUDED.answer_base_url, answer_api_key=EXCLUDED.answer_api_key, "
                "answer_model=EXCLUDED.answer_model, rewrite_base_url=EXCLUDED.rewrite_base_url, "
                "rewrite_api_key=EXCLUDED.rewrite_api_key, rewrite_model=EXCLUDED.rewrite_model"
            )
        )
        await conn.commit()
    await eng.dispose()

    _alembic_upgrade(temp_db, REV_A, openai_api_key="K_OAI")

    # api_keys SHALL contain at least one Hub row and one OpenAI row
    keys = await _all(
        temp_db, "SELECT provider, api_key FROM api_keys"
    )
    providers_to_keys = {p: k for (p, k) in keys}
    assert providers_to_keys.get("zeabur-aihub") == "K_HUB"
    assert providers_to_keys.get("openai") == "K_OAI"

    # ai_steps.answer points at the Hub row with gpt-4o
    answer = await _all(
        temp_db,
        "SELECT s.base_url, s.model, k.provider FROM ai_steps s "
        "LEFT JOIN api_keys k ON k.id = s.api_key_id WHERE s.step_key='answer'",
    )
    assert answer == [("https://hnd1.aihub.zeabur.ai/v1", "gpt-4o", "zeabur-aihub")]

    # ai_steps.embedding points at the OpenAI row
    embedding = await _all(
        temp_db,
        "SELECT s.base_url, s.model, k.provider FROM ai_steps s "
        "LEFT JOIN api_keys k ON k.id = s.api_key_id WHERE s.step_key='embedding'",
    )
    assert embedding == [
        ("https://api.openai.com/v1", "text-embedding-3-small", "openai"),
    ]

    # ai_steps.summary intentionally left blank
    summary = await _all(
        temp_db,
        "SELECT base_url, model, api_key_id FROM ai_steps WHERE step_key='summary'",
    )
    assert summary == [(None, None, None)]


@db_required
@pytest.mark.asyncio
async def test_rev_b_drops_llm_config(temp_db):
    """Task 8.3 — after Rev A + Rev B, llm_config is gone."""
    _alembic_upgrade(temp_db, REV_A, openai_api_key="sk-rev-b")
    assert await _scalar(temp_db, "SELECT to_regclass('llm_config') IS NOT NULL")

    _alembic_upgrade(temp_db, REV_B, openai_api_key="sk-rev-b")
    assert await _scalar(temp_db, "SELECT to_regclass('llm_config') IS NULL")
    # ai_steps and api_keys SHALL still exist
    assert await _scalar(temp_db, "SELECT to_regclass('ai_steps') IS NOT NULL")
    assert await _scalar(temp_db, "SELECT to_regclass('api_keys') IS NOT NULL")
