"""jieba tokeniser backed by `tokenizer_custom_terms` DB rows.

Public API:
- `tokenize(text)` — sync, returns list[str]. Lazy-loads dictionary on first
  call if it has not yet been initialised by an explicit `load_dictionary` /
  `reload_dictionary`.
- `async load_dictionary(db)` — initial load from DB; idempotent.
- `async reload_dictionary(db)` — clear current custom terms and re-register
  from DB. Used by admin reload endpoint + Celery broadcast.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import jieba
from sqlalchemy import select

from app.models.tokenizer_term import TokenizerCustomTerm

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_loaded_terms: set[str] = set()
_loaded: bool = False
_lock = threading.Lock()


def tokenize(text: str) -> list[str]:
    """Return jieba tokens for the input string.

    The first invocation triggers a lazy DB load using a synchronous
    connection; in async contexts callers should normally call
    `await load_dictionary(db)` at startup so that this lazy path is never
    exercised.
    """
    if not _loaded:
        _lazy_sync_load()

    stripped = text.strip()
    if not stripped:
        return []
    tokens = [t for t in jieba.cut(stripped, cut_all=False) if t.strip()]
    return tokens


async def load_dictionary(db: AsyncSession) -> int:
    """Load custom terms from DB and register with jieba. Idempotent."""
    global _loaded
    with _lock:
        if _loaded:
            return len(_loaded_terms)
        await _register_from_db(db)
        _loaded = True
    return len(_loaded_terms)


async def reload_dictionary(db: AsyncSession) -> int:
    """Clear current custom terms and reload from DB."""
    global _loaded
    with _lock:
        for term in list(_loaded_terms):
            jieba.del_word(term)
        _loaded_terms.clear()
        await _register_from_db(db)
        _loaded = True
    return len(_loaded_terms)


async def _register_from_db(db: AsyncSession) -> None:
    rows = (await db.execute(select(TokenizerCustomTerm))).scalars().all()
    for row in rows:
        jieba.add_word(row.term, freq=row.weight)
        _loaded_terms.add(row.term)
    logger.info("tokenizer dictionary loaded: %d terms", len(_loaded_terms))


def _lazy_sync_load() -> None:
    """Synchronous fallback used when `tokenize()` is called before any
    explicit async `load_dictionary` has run (e.g. from sync test code or
    a script). Uses a transient sync engine derived from settings."""
    global _loaded
    with _lock:
        if _loaded:
            return
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session

            from app.core.config import settings

            sync_url = settings.database_url.replace("+asyncpg", "")
            engine = create_engine(sync_url, future=True)
            with Session(engine) as session:
                rows = session.execute(select(TokenizerCustomTerm)).scalars().all()
                for row in rows:
                    jieba.add_word(row.term, freq=row.weight)
                    _loaded_terms.add(row.term)
            engine.dispose()
            logger.info(
                "tokenizer dictionary lazy-loaded (sync): %d terms",
                len(_loaded_terms),
            )
        except Exception:
            logger.exception("lazy sync tokenizer load failed; continuing without dict")
        _loaded = True


def reset_for_tests() -> None:
    """Test helper: forget all custom terms and mark as unloaded."""
    global _loaded
    with _lock:
        for term in list(_loaded_terms):
            jieba.del_word(term)
        _loaded_terms.clear()
        _loaded = False
