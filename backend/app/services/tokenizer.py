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

from app.models.show import Show
from app.models.tokenizer_term import TokenizerCustomTerm

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_loaded_terms: set[str] = set()
_show_name_terms: set[str] = set()
_loaded: bool = False
_lock = threading.Lock()


def get_show_name_terms() -> set[str]:
    """Return show-name terms auto-derived from `shows.title`.

    Used by `rag._build_ts_query` to drop show-name tokens from the
    lexical query side (embedding side is not affected). The
    `tokenizer_custom_terms.is_show_name` column is no longer consulted;
    show names come from the canonical `shows` table.
    """
    return _show_name_terms.copy()


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


def title_tsv_text(title: str | None) -> str:
    """Jieba-tokenise an episode title and return the space-joined token
    stream used by `to_tsvector('simple', :tsv_text)`.

    R3.3 Phase 8 follow-up: episodes.title_tsvector is populated Python-side
    on insert / title-change update (mirrors the R3.1 pattern used for
    transcript_chunks.text_tsvector and episode_description_chunks.text_tsvector).
    Returns "" for blank / None input so callers can write a NULL-equivalent
    empty tsvector without branching.
    """
    if not title:
        return ""
    tokens = tokenize(title)
    return " ".join(t for t in tokens if t and t.strip())


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
        _show_name_terms.clear()
        await _register_from_db(db)
        _loaded = True
    return len(_loaded_terms)


async def _register_from_db(db: AsyncSession) -> None:
    rows = (await db.execute(select(TokenizerCustomTerm))).scalars().all()
    _show_name_terms.clear()
    for row in rows:
        jieba.add_word(row.term, freq=row.weight)
        _loaded_terms.add(row.term)
    show_titles = (await db.execute(select(Show.title))).scalars().all()
    for title in show_titles:
        if not title:
            continue
        jieba.add_word(title)
        _loaded_terms.add(title)
        _show_name_terms.add(title)
    logger.info(
        "tokenizer dictionary loaded: %d terms (%d show-name auto-derived)",
        len(_loaded_terms),
        len(_show_name_terms),
    )


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
                _show_name_terms.clear()
                for row in rows:
                    jieba.add_word(row.term, freq=row.weight)
                    _loaded_terms.add(row.term)
                show_titles = session.execute(select(Show.title)).scalars().all()
                for title in show_titles:
                    if not title:
                        continue
                    jieba.add_word(title)
                    _loaded_terms.add(title)
                    _show_name_terms.add(title)
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
        _show_name_terms.clear()
        _loaded = False
