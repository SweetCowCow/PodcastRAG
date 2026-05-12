"""Provider API key resolver — for offline / standalone scripts ONLY.

In-request paths (FastAPI handlers, embedding.py / rag.py / whisper_provider.py
etc.) MUST keep using `step_config.api_key` via `ai_step_resolver`. This module
exists to give *offline scripts* (bake-offs, backfills, eval runners) a single
consistent way to obtain the right provider key, instead of every script doing
its own `os.environ["OPENAI_API_KEY"]` lookup (which hits the AI Hub gateway
key — wrong key for embeddings).

Resolution order for `get_provider_key(provider, prefer_env=...)`:

  1. If `prefer_env` is set AND `os.environ[prefer_env]` is non-empty → return it.
  2. Cache hit on `(provider, prefer_env)` → return cached value.
  3. DB: SELECT api_key FROM api_keys WHERE provider = :p
         ORDER BY created_at DESC LIMIT 1
     → cache + return.
  4. Raise `KeyError(f"No API key found for provider={provider!r}")`.

Logging discipline: this module NEVER prints or logs an API key value, in any
path (success / miss / cache hit / exception). Tests assert this via caplog.

Note on implementation choice (deviation from design D3):
    Design D3 prescribed a *sync* SQLAlchemy engine for offline use. The
    project, however, only ships `asyncpg` as its Postgres driver — no
    `psycopg` / `psycopg2` is installed (see backend/requirements.txt). Adding
    a sync driver would expand the build surface for a small utility. Instead,
    we keep the public API sync (callers see a plain `get_provider_key()`) and
    wrap the async engine with `asyncio.run` internally. Behaviour is the same;
    only the driver path differs.
"""
from __future__ import annotations

import asyncio
import os
import threading
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

# Module-level cache. Key is the (provider, prefer_env) tuple so that two
# callers asking for the same provider via different env-var override names
# don't collide. We only cache DB hits — env hits are recomputed each call so
# devs can `export` mid-process to debug.
_CACHE: dict[tuple[str, Optional[str]], str] = {}


def _resolve_from_env(prefer_env: Optional[str]) -> Optional[str]:
    """Return env var value if set and non-empty, else None.

    Intentionally does not log the value (or even its existence beyond the
    boolean return). Matches D5 logging discipline.
    """
    if not prefer_env:
        return None
    value = os.environ.get(prefer_env)
    if value:
        return value
    return None


async def _resolve_from_db(provider: str) -> Optional[str]:
    """Query api_keys table for latest row matching provider.

    Builds a dedicated async engine for this call rather than reusing the
    app-level `AsyncSessionFactory`. The app engine is bound to whichever event
    loop first touches it (typically the ASGI worker loop); calling it from a
    different loop (e.g. the throwaway loop we spawn for sync callers) leads to
    "Event loop is closed" errors during connection teardown. A short-lived
    engine sidesteps that entirely.

    Returns the raw api_key string, or None if no row found. Never logs the
    value. Any DB connection error propagates to the caller unchanged.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Maker() as session:
            result = await session.execute(
                text(
                    "SELECT api_key FROM api_keys "
                    "WHERE provider = :provider "
                    "ORDER BY created_at DESC "
                    "LIMIT 1"
                ),
                {"provider": provider},
            )
            row = result.first()
            if row is None:
                return None
            return row[0]
    finally:
        await engine.dispose()


def get_provider_key(provider: str, prefer_env: Optional[str] = None) -> str:
    """Resolve provider API key for offline / standalone scripts.

    Args:
        provider: matches api_keys.provider column, e.g. 'openai'.
        prefer_env: optional env var name consulted before DB. Convention is
            to use a distinct name from default (e.g. 'OPENAI_OFFICIAL_KEY')
            to avoid collision with OPENAI_API_KEY (AI Hub gateway key).

    Returns:
        Raw API key string.

    Raises:
        KeyError: when no key is found in env or DB. Message contains the
            provider name only — never the key value.
    """
    # Step 1: env override (always rechecked, not cached, per D2).
    env_value = _resolve_from_env(prefer_env)
    if env_value is not None:
        return env_value

    # Step 2: cache lookup for DB-sourced keys.
    cache_key = (provider, prefer_env)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Step 3: DB lookup. Run on a dedicated thread with its own event loop so
    # the call works whether the caller is plain-sync (the primary use case)
    # OR happens to already sit inside a running event loop (e.g. when invoked
    # from an async test or notebook). Without this, asyncio.run() would crash
    # with "cannot be called from a running event loop".
    db_value: Optional[str] = None
    error_box: list[BaseException] = []

    def _runner() -> None:
        nonlocal db_value
        try:
            db_value = asyncio.run(_resolve_from_db(provider))
        except BaseException as exc:  # noqa: BLE001 — re-raise on main thread
            error_box.append(exc)

    thread = threading.Thread(target=_runner, name="key-resolver-db", daemon=True)
    thread.start()
    thread.join()
    if error_box:
        raise error_box[0]
    if db_value is not None:
        _CACHE[cache_key] = db_value
        return db_value

    # Step 4: miss. Note: KeyError message MUST NOT include any key value;
    # only the provider name. Tests pin this exact format.
    raise KeyError(f"No API key found for provider={provider!r}")


def _reset_cache_for_tests() -> None:
    """Clear the module-level cache. Intended for test fixtures only."""
    _CACHE.clear()
