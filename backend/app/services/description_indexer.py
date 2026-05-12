"""Build the per-episode RSS description index.

For each episode with a non-empty `description`:
  1. Strip HTML (stdlib `html.parser`).
  2. Strip boilerplate lines via `BOILERPLATE_PATTERNS` (case-insensitive,
     line-level).
  3. Skip + delete-existing-row when nothing useful remains.
  4. Otherwise: jieba-tokenise, OpenAI-embed, UPSERT one row keyed by
     `episode_id`.
"""
from __future__ import annotations

import logging
import re
import uuid
from html.parser import HTMLParser

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.episode_description_chunk import EpisodeDescriptionChunk
from app.services import tokenizer
from app.services.ai_step_resolver import get_step_config
from app.services.embedding import embed_texts, embed_texts_dual

logger = logging.getLogger(__name__)

# Regex patterns matched per-line (case-insensitive). A matching line is
# removed entirely. Conservative seed list — anything more aggressive should
# wait for an admin-managed table (out of R3.1 scope).
BOILERPLATE_PATTERNS: list[str] = [
    r".*鼓勵.*贊助.*",
    r".*按讚訂閱.*",
    r".*歡迎收聽下集.*",
]

_BOILERPLATE_RE = [re.compile(p, re.IGNORECASE) for p in BOILERPLATE_PATTERNS]


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):  # noqa: ANN001 (stdlib signature)
        if tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):  # noqa: ANN001
        if self._skip_depth:
            return
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html(s: str) -> str:
    p = _Stripper()
    p.feed(s)
    p.close()
    text = p.get_text()
    # Collapse runs of whitespace within a line, preserve newlines
    lines = [re.sub(r"[\t ]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(lines).strip()


def _strip_boilerplate(s: str) -> str:
    kept: list[str] = []
    for line in s.splitlines():
        if any(rx.match(line) for rx in _BOILERPLATE_RE):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def clean_description(raw: str | None) -> str:
    if not raw:
        return ""
    return _strip_boilerplate(_strip_html(raw))


async def build_description_index_for_episode(
    db: AsyncSession,
    episode_id: uuid.UUID,
    *,
    chunking_version: int = 1,
    chunk_index: int = 0,
) -> str:
    """Build/UPSERT a description chunk row for one episode.

    `chunking_version` defaults to 1 (whole-description v1 behaviour, used by
    every existing caller without change). Pilot re-chunk drivers pass
    `chunking_version=2` + an explicit `chunk_index` to write v2 rows alongside
    the v1 row (composite unique on `(episode_id, chunking_version,
    chunk_index)` keeps writes deterministic).

    Returns: 'inserted' | 'updated' | 'skipped' | 'deleted_empty'
    """
    episode = await db.get(Episode, episode_id)
    if episode is None:
        logger.warning("episode %s not found; skip", episode_id)
        return "skipped"

    raw = episode.description or ""
    raw_len = len(raw)
    cleaned = clean_description(raw)
    cleaned_len = len(cleaned)

    if raw_len > 0 and cleaned_len < raw_len * 0.5:
        logger.warning(
            "description strip > 50%%: episode=%s raw=%d cleaned=%d",
            episode_id,
            raw_len,
            cleaned_len,
        )

    if not cleaned:
        # Delete only the same-version row; never touch the other version.
        existing = (
            await db.execute(
                select(EpisodeDescriptionChunk).where(
                    EpisodeDescriptionChunk.episode_id == episode_id,
                    EpisodeDescriptionChunk.chunking_version == chunking_version,
                    EpisodeDescriptionChunk.chunk_index == chunk_index,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            await db.execute(
                delete(EpisodeDescriptionChunk).where(
                    EpisodeDescriptionChunk.episode_id == episode_id,
                    EpisodeDescriptionChunk.chunking_version == chunking_version,
                    EpisodeDescriptionChunk.chunk_index == chunk_index,
                )
            )
            await db.commit()
            return "deleted_empty"
        return "skipped"

    # Build embedding via the embedding step (always OpenAI).
    # r3-4 dual-write: populate both legacy (1536) and v2 (3072) columns.
    embedding_cfg = await get_step_config(db, "embedding")
    legacy_vecs, v2_vecs = embed_texts_dual([cleaned], embedding_cfg)
    embedding = legacy_vecs[0] if legacy_vecs else None
    embedding_v2 = v2_vecs[0] if v2_vecs else None

    # Tokenise; tsvector populated server-side via `to_tsvector('simple', ...)`.
    await tokenizer.load_dictionary(db)
    tokens = tokenizer.tokenize(cleaned)
    tsv_text = " ".join(tokens)

    existing = (
        await db.execute(
            select(EpisodeDescriptionChunk).where(
                EpisodeDescriptionChunk.episode_id == episode_id,
                EpisodeDescriptionChunk.chunking_version == chunking_version,
                EpisodeDescriptionChunk.chunk_index == chunk_index,
            )
        )
    ).scalar_one_or_none()

    stmt = pg_insert(EpisodeDescriptionChunk.__table__).values(
        episode_id=episode_id,
        chunking_version=chunking_version,
        chunk_index=chunk_index,
        text=cleaned,
        embedding=embedding,
        embedding_v2=embedding_v2,
        text_tsvector=func.to_tsvector("simple", tsv_text),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            EpisodeDescriptionChunk.episode_id,
            EpisodeDescriptionChunk.chunking_version,
            EpisodeDescriptionChunk.chunk_index,
        ],
        set_={
            "text": stmt.excluded.text,
            "embedding": stmt.excluded.embedding,
            "embedding_v2": stmt.excluded.embedding_v2,
            "text_tsvector": stmt.excluded.text_tsvector,
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)
    await db.commit()
    return "updated" if existing is not None else "inserted"
