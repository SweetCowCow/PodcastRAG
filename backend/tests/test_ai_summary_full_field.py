"""R2.1 followup: ai_summary_full field tests.

Covers task 1.3 of `r2-1-followup-bugs`:
- enrich_hits populates BOTH `ai_summary_excerpt` (60-char truncated) and
  `ai_summary_full` (untruncated) when the episode has an ai_summary.
- When the episode has no ai_summary (None / empty / whitespace),
  `ai_summary_excerpt == ""` AND `ai_summary_full is None`.
- ChunkHit pydantic schema accepts and round-trips `ai_summary_full`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.schemas.query import ChunkHit as SchemaChunkHit
from app.services import rag


# ---------------------------------------------------------------------------
# Minimal fake AsyncSession (mirrors the one in
# test_rag_query_response_shape.py) so the suite stays Postgres-free.
# ---------------------------------------------------------------------------


@dataclass
class _FakeResult:
    rows: list[dict]

    def mappings(self) -> "_FakeResult":
        return self

    def first(self) -> dict | None:
        return self.rows[0] if self.rows else None


@dataclass
class _FakeDB:
    context_rows: dict[uuid.UUID, dict] = field(default_factory=dict)
    summary_rows: dict[uuid.UUID, dict] = field(default_factory=dict)
    highlight_row: dict | None = None

    async def execute(self, sql, params: dict[str, Any]):
        s = str(sql)
        if "transcript_segments" in s and "prev_segs" in s:
            row = self.context_rows.get(
                params["chunk_id"], {"before_text": "", "after_text": ""}
            )
            return _FakeResult([row])
        if "ts_headline" in s:
            return _FakeResult(
                [self.highlight_row] if self.highlight_row else []
            )
        if "ai_summary" in s and "FROM episodes" in s:
            row = self.summary_rows.get(
                params["episode_id"], {"ai_summary": None}
            )
            return _FakeResult([row])
        raise AssertionError(f"unexpected SQL: {s[:80]}")


def _make_hit(
    *,
    source: str = "transcript",
    text: str = "段落內容",
    chunk_id: uuid.UUID | None = None,
    episode_id: uuid.UUID | None = None,
) -> rag.ChunkHit:
    return rag.ChunkHit(
        episode_id=episode_id or uuid.uuid4(),
        episode_title="EP1",
        start_time=0.0,
        end_time=10.0,
        text=text,
        chunk_id=chunk_id or (uuid.uuid4() if source == "transcript" else None),
        source=source,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Schema-level: pydantic model accepts new field, defaults to None.
# ---------------------------------------------------------------------------


def test_chunk_hit_schema_defaults_ai_summary_full_to_none():
    hit = SchemaChunkHit(
        episode_id=uuid.uuid4(),
        episode_title="EP1",
        start_time=0.0,
        end_time=10.0,
        text="x",
    )
    assert hit.ai_summary_full is None


def test_chunk_hit_schema_round_trips_full_summary():
    hit = SchemaChunkHit(
        episode_id=uuid.uuid4(),
        episode_title="EP1",
        start_time=0.0,
        end_time=10.0,
        text="x",
        ai_summary_excerpt="前 60 字" + "迪" * 50 + "…",
        ai_summary_full="完整摘要" * 50,
    )
    dumped = hit.model_dump()
    assert dumped["ai_summary_full"] == "完整摘要" * 50
    assert dumped["ai_summary_excerpt"].endswith("…")


# ---------------------------------------------------------------------------
# enrich_hits: 200-char summary → excerpt 60+…，full = 整段
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_populates_excerpt_and_full_when_summary_present():
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    full_text = "迪" * 200  # 200 chars, well past the 60-char excerpt cap
    db = _FakeDB(
        context_rows={chunk_id: {"before_text": "", "after_text": ""}},
        summary_rows={episode_id: {"ai_summary": full_text}},
        highlight_row=None,
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "")
    # excerpt = first 60 + ellipsis
    assert hit.ai_summary_excerpt == "迪" * 60 + "…"
    assert len(hit.ai_summary_excerpt) == 61
    # full = untruncated, exactly 200 chars
    assert hit.ai_summary_full == full_text
    assert len(hit.ai_summary_full) == 200


@pytest.mark.asyncio
async def test_enrich_strips_whitespace_in_full_summary():
    """A summary surrounded by whitespace gets stripped on both excerpt and full."""
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    db = _FakeDB(
        context_rows={chunk_id: {"before_text": "", "after_text": ""}},
        summary_rows={episode_id: {"ai_summary": "   有效摘要   "}},
        highlight_row=None,
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "")
    assert hit.ai_summary_full == "有效摘要"
    assert hit.ai_summary_excerpt == "有效摘要"


# ---------------------------------------------------------------------------
# enrich_hits: missing summary → excerpt "" + full None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_with_no_summary_returns_none_full():
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    db = _FakeDB(
        context_rows={chunk_id: {"before_text": "", "after_text": ""}},
        summary_rows={episode_id: {"ai_summary": None}},
        highlight_row=None,
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "")
    assert hit.ai_summary_excerpt == ""
    assert hit.ai_summary_full is None


@pytest.mark.asyncio
async def test_enrich_with_empty_summary_returns_none_full():
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    db = _FakeDB(
        context_rows={chunk_id: {"before_text": "", "after_text": ""}},
        summary_rows={episode_id: {"ai_summary": "   "}},
        highlight_row=None,
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "")
    assert hit.ai_summary_excerpt == ""
    assert hit.ai_summary_full is None


@pytest.mark.asyncio
async def test_enrich_with_short_summary_full_equals_excerpt():
    """Summaries already <= 60 chars: full == excerpt (no ellipsis)."""
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    short = "短摘要 30 字以內"
    db = _FakeDB(
        context_rows={chunk_id: {"before_text": "", "after_text": ""}},
        summary_rows={episode_id: {"ai_summary": short}},
        highlight_row=None,
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "")
    assert hit.ai_summary_excerpt == short
    assert hit.ai_summary_full == short
    assert "…" not in hit.ai_summary_full
