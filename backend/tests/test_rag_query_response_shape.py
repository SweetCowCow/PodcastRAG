"""R2.1 citation infra: response-shape tests for `/search` and `/query`.

These tests cover the new fields added to `ChunkHit` (`before_text`,
`after_text`, `highlights`, `ai_summary_excerpt`) and the new top-level
`sources_schema_version` field. We test pure-Python helpers and the
`enrich_hits` orchestration against a faked AsyncSession so the suite
runs without a live Postgres.

Scenarios mapped from `openspec/changes/r2-1-citation-infra/specs/rag-query/spec.md`:
- Transcript source includes two-segment context → `test_enrich_transcript_hit_has_context`
- First chunk has empty before_text → `test_enrich_first_chunk_empty_before`
- Description source has empty context fields → `test_enrich_description_hit_empty_before_after`
- Highlights wrap matched tokens → `test_enrich_highlight_wraps_with_mark`
- AI summary excerpt truncates with ellipsis → `test_truncate_ai_summary_truncates`
- Episode without AI summary returns empty excerpt → `test_truncate_ai_summary_empty`
- Response carries sources schema version → `test_search_and_chat_response_carry_schema_version`
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.schemas.query import (
    SOURCES_SCHEMA_VERSION,
    ChatResponse,
    ChunkHit as SchemaChunkHit,
    PublicSearchResponse,
    SearchResponse,
)
from app.services import rag


# ---------------------------------------------------------------------------
# Fake AsyncSession that returns canned rows for the three SQL helpers.
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
    """Routes queries by inspecting the SQL text snippet.

    `context_rows` keyed by chunk_id, `summary_rows` keyed by episode_id,
    `highlight_rows` is a single canned row used for any ts_headline call.
    """

    context_rows: dict[uuid.UUID, dict] = field(default_factory=dict)
    summary_rows: dict[uuid.UUID, dict] = field(default_factory=dict)
    highlight_row: dict | None = None
    calls: list[str] = field(default_factory=list)

    async def execute(self, sql, params: dict[str, Any]):
        s = str(sql)
        self.calls.append(s)
        if "transcript_segments" in s and "prev_segs" in s:
            row = self.context_rows.get(params["chunk_id"], {
                "before_text": "",
                "after_text": "",
            })
            return _FakeResult([row])
        if "ts_headline" in s:
            return _FakeResult([self.highlight_row] if self.highlight_row else [])
        if "ai_summary" in s and "FROM episodes" in s:
            row = self.summary_rows.get(params["episode_id"], {"ai_summary": None})
            return _FakeResult([row])
        raise AssertionError(f"unexpected SQL routed in fake DB: {s[:80]}")


def _make_hit(
    *,
    source: str = "transcript",
    text: str = "歌單環節 開始 播 三首歌",
    chunk_id: uuid.UUID | None = None,
    episode_id: uuid.UUID | None = None,
) -> rag.ChunkHit:
    return rag.ChunkHit(
        episode_id=episode_id or uuid.uuid4(),
        episode_title="EP1",
        start_time=10.0,
        end_time=20.0,
        text=text,
        chunk_id=chunk_id or (uuid.uuid4() if source == "transcript" else None),
        source=source,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Pure-helper tests (no DB).
# ---------------------------------------------------------------------------


def test_truncate_ai_summary_truncates():
    # 80-char string per spec scenario "AI summary excerpt truncates with ellipsis"
    summary = "迪" * 80
    excerpt = rag._truncate_ai_summary(summary, max_chars=60)
    assert excerpt == "迪" * 60 + "…"
    # Single ellipsis only — no double `……` or `...`
    assert excerpt.count("…") == 1


def test_truncate_ai_summary_empty():
    assert rag._truncate_ai_summary(None) == ""
    assert rag._truncate_ai_summary("") == ""
    assert rag._truncate_ai_summary("   ") == ""


def test_truncate_ai_summary_short_unchanged():
    assert rag._truncate_ai_summary("短摘要") == "短摘要"


def test_strip_non_mark_tags_keeps_mark():
    src = "前文 <mark>歌單</mark> 後面 <script>x</script> <b>bold</b>"
    out = rag._strip_non_mark_tags(src)
    assert "<mark>歌單</mark>" in out
    assert "<script>" not in out
    assert "<b>" not in out


# ---------------------------------------------------------------------------
# enrich_hits orchestration tests (faked DB).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_transcript_hit_has_context():
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    db = _FakeDB(
        context_rows={chunk_id: {"before_text": "s3 s4", "after_text": "s8 s9"}},
        summary_rows={episode_id: {"ai_summary": "迪拉胖在這集邀請了顏色一起聊"}},
        highlight_row={"highlight": "前文 <mark>歌單</mark> 後文"},
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "這集有歌單嗎")
    assert hit.before_text == "s3 s4"
    assert hit.after_text == "s8 s9"
    assert "<mark>歌單</mark>" in hit.highlights
    assert hit.ai_summary_excerpt == "迪拉胖在這集邀請了顏色一起聊"


@pytest.mark.asyncio
async def test_enrich_first_chunk_empty_before():
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    db = _FakeDB(
        # First chunk: no preceding segments — DB returns empty before_text.
        context_rows={chunk_id: {"before_text": "", "after_text": "s2 s3"}},
        summary_rows={episode_id: {"ai_summary": None}},
        highlight_row={"highlight": ""},
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "歌單")
    assert hit.before_text == ""
    assert hit.after_text == "s2 s3"


@pytest.mark.asyncio
async def test_enrich_description_hit_empty_before_after():
    episode_id = uuid.uuid4()
    db = _FakeDB(
        summary_rows={episode_id: {"ai_summary": "節目簡介"}},
        highlight_row={"highlight": "節目 <mark>歌單</mark> 介紹"},
    )
    hit = _make_hit(source="description", chunk_id=None, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "歌單")
    assert hit.before_text == ""
    assert hit.after_text == ""
    # Highlight still computed against description text.
    assert "<mark>" in hit.highlights


@pytest.mark.asyncio
async def test_enrich_highlight_wraps_with_mark_only():
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    # Adversarial: ts_headline output happens to contain a stray <b> tag —
    # `_strip_non_mark_tags` must remove it.
    db = _FakeDB(
        context_rows={chunk_id: {"before_text": "", "after_text": ""}},
        summary_rows={episode_id: {"ai_summary": None}},
        highlight_row={
            "highlight": "前 <mark>歌單</mark> 後 <b>不該出現</b>"
        },
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    await rag.enrich_hits(db, [hit], "歌單")
    assert "<mark>歌單</mark>" in hit.highlights
    assert "<b>" not in hit.highlights


@pytest.mark.asyncio
async def test_enrich_no_question_skips_highlight():
    """When no usable lexical query exists, `highlights` stays empty."""
    chunk_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    db = _FakeDB(
        context_rows={chunk_id: {"before_text": "a", "after_text": "b"}},
        summary_rows={episode_id: {"ai_summary": None}},
        highlight_row={"highlight": "should not be returned"},
    )
    hit = _make_hit(chunk_id=chunk_id, episode_id=episode_id)
    # Empty question → ts_query is None → highlight short-circuits to "".
    await rag.enrich_hits(db, [hit], "")
    assert hit.highlights == ""


# ---------------------------------------------------------------------------
# Response-envelope shape tests.
# ---------------------------------------------------------------------------


def test_search_and_chat_response_carry_schema_version():
    """Every response envelope ships `sources_schema_version=1` by default."""
    assert SOURCES_SCHEMA_VERSION == 1
    pub = PublicSearchResponse(results=[])
    assert pub.sources_schema_version == 1
    sr = SearchResponse(results=[], quota_remaining=10)
    assert sr.sources_schema_version == 1
    cr = ChatResponse(
        query_id="abc", answer="x", citations=[], quota_remaining=10
    )
    assert cr.sources_schema_version == 1
    # citations_meta defaults to empty list (no inline refs parsed yet).
    assert cr.citations_meta == []


def test_chunk_hit_defaults_for_new_fields():
    """ChunkHit constructed without the new fields stays valid (back-compat)."""
    hit = SchemaChunkHit(
        episode_id=uuid.uuid4(),
        episode_title="EP1",
        start_time=0.0,
        end_time=10.0,
        text="…",
    )
    assert hit.before_text == ""
    assert hit.after_text == ""
    assert hit.highlights == ""
    assert hit.ai_summary_excerpt == ""
