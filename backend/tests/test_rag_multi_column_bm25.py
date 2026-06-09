"""R3.3 Phase 8: three-pool RRF (chunk + description + title) + metadata filter.

Verifies:
- `RRF_WEIGHTS` matches design defaults (chunk 1.0 / desc 0.7 / title 0.5)
- weighted RRF math: same-rank hits across pools sort by weight
- SQL templates carry the new `:weight_*` and `{metadata_filter}` placeholders
- `_metadata_filter_clause` binds `guests` (JSONB containment) and
  `date_range` (BETWEEN) only when set; empty / None → "" clause
- `MetadataFilters.is_empty()` true for default ctor
- `retrieve_titles` returns empty list when ts_query is unusable
- `retrieve_hybrid` merge orders three-pool hits by RRF score; title hits
  with `chunk_id=None` bypass the chunk_id dedupe set
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.services import rag, rag_retrieval, tokenizer


# ---------------------------------------------------------------------------
# 8.1: RRF_WEIGHTS constant
# ---------------------------------------------------------------------------

def test_rrf_weights_match_design_defaults():
    assert rag.RRF_WEIGHTS == {"chunk": 1.0, "description": 0.7, "title": 0.5}


def test_title_per_side_smaller_than_chunk_per_side():
    """Title corpus is one-row-per-episode; per_side cap should stay small."""
    assert rag.TITLE_RRF_PER_SIDE < rag.RRF_PER_SIDE


# ---------------------------------------------------------------------------
# 8.2 / 8.3: SQL templates carry weight + metadata_filter placeholders
# ---------------------------------------------------------------------------

def test_transcript_sql_has_weight_chunk_and_metadata_placeholder():
    assert ":weight_chunk" in rag._TRANSCRIPT_RRF_SQL
    assert "{metadata_filter}" in rag._TRANSCRIPT_RRF_SQL
    assert "{metadata_filter}" in rag._TRANSCRIPT_SEMANTIC_ONLY_SQL


def test_desc_sql_has_weight_desc_and_metadata_placeholder():
    assert ":weight_desc" in rag._DESC_RRF_SQL
    assert "{metadata_filter}" in rag._DESC_RRF_SQL
    assert "{metadata_filter}" in rag._DESC_SEMANTIC_ONLY_SQL


def test_title_sql_has_weight_title_and_metadata_placeholder():
    assert ":weight_title" in rag._TITLE_LEXICAL_SQL
    assert "{metadata_filter}" in rag._TITLE_LEXICAL_SQL
    assert "title_tsvector" in rag._TITLE_LEXICAL_SQL


# ---------------------------------------------------------------------------
# 8.2: weighted RRF math
# ---------------------------------------------------------------------------

def _weighted_rrf(rank_s: int | None, rank_l: int | None, w: float, k: int = 60) -> float:
    s = 1.0 / (k + (rank_s if rank_s is not None else 999))
    lex = w * 1.0 / (k + (rank_l if rank_l is not None else 999))
    return s + lex


def test_weighted_rrf_chunk_pool_full_weight():
    """Spec example: chunk A (rank_s=3, rank_l=25), weight_chunk=1.0."""
    score = _weighted_rrf(3, 25, w=rag.RRF_WEIGHTS["chunk"])
    assert score == pytest.approx(1 / 63 + 1.0 * 1 / 85)


def test_weighted_rrf_desc_pool_attenuates():
    """Desc pool at the same ranks should score lower than chunk pool."""
    score_chunk = _weighted_rrf(3, 25, w=rag.RRF_WEIGHTS["chunk"])
    score_desc = _weighted_rrf(3, 25, w=rag.RRF_WEIGHTS["description"])
    assert score_desc < score_chunk
    assert score_desc == pytest.approx(1 / 63 + 0.7 * 1 / 85)


def test_three_pool_ordering_at_equal_lexical_rank():
    """Same lexical rank across three pools sorts chunk > desc > title."""
    # Title pool has no semantic side; simulate by setting rank_s=None.
    chunk_score = _weighted_rrf(None, 1, w=rag.RRF_WEIGHTS["chunk"])
    desc_score = _weighted_rrf(None, 1, w=rag.RRF_WEIGHTS["description"])
    title_score = rag.RRF_WEIGHTS["title"] * 1.0 / (60 + 1)
    assert chunk_score > desc_score > title_score


# ---------------------------------------------------------------------------
# 8.4 / 8.5: MetadataFilters + _metadata_filter_clause
# ---------------------------------------------------------------------------

def test_metadata_filters_empty_by_default():
    mf = rag.MetadataFilters()
    assert mf.is_empty() is True
    assert mf.guests == []
    assert mf.date_range is None


def test_metadata_filters_not_empty_when_guest_set():
    assert rag.MetadataFilters(guests=["馬世芳"]).is_empty() is False


def test_metadata_filters_not_empty_when_date_set():
    rng = (
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
    )
    assert rag.MetadataFilters(date_range=rng).is_empty() is False


def test_metadata_filter_clause_empty_returns_blank():
    params: dict = {}
    out = rag._metadata_filter_clause("e", params, None)
    assert out == ""
    assert params == {}

    out = rag._metadata_filter_clause("e", params, rag.MetadataFilters())
    assert out == ""
    assert params == {}


def test_metadata_filter_clause_guest_binds_jsonb_string():
    """Guests filter MUST bind as JSON-encoded string for CAST AS jsonb."""
    params: dict = {}
    mf = rag.MetadataFilters(guests=["馬世芳"])
    out = rag._metadata_filter_clause("e", params, mf)
    assert "e.guests @> CAST(:metadata_guests AS jsonb)" in out
    assert out.startswith("AND ")
    # Param is JSON-encoded so PG can cast it as jsonb.
    assert params["metadata_guests"] == '["\\u99ac\\u4e16\\u82b3"]' or \
        params["metadata_guests"] == '["馬世芳"]'


def test_metadata_filter_clause_date_range_binds_endpoints():
    params: dict = {}
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    mf = rag.MetadataFilters(date_range=(start, end))
    out = rag._metadata_filter_clause("e", params, mf)
    assert "e.published_at BETWEEN :metadata_date_start AND :metadata_date_end" in out
    assert params["metadata_date_start"] == start
    assert params["metadata_date_end"] == end


def test_metadata_filter_clause_combines_guest_and_date_with_and():
    params: dict = {}
    mf = rag.MetadataFilters(
        guests=["馬世芳"],
        date_range=(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 12, 31, tzinfo=timezone.utc),
        ),
    )
    out = rag._metadata_filter_clause("e", params, mf)
    # Both clauses present, joined by AND, single leading AND.
    assert out.count("AND") >= 2
    assert "e.guests" in out
    assert "e.published_at" in out


# ---------------------------------------------------------------------------
# 8.3: retrieve_titles short-circuits on unusable ts_query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrieve_titles_empty_on_blank_question():
    tokenizer.reset_for_tests()
    db = AsyncMock()
    out = await rag.retrieve_titles(db, uuid.uuid4(), question="")
    assert out == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_titles_empty_on_pure_punctuation():
    tokenizer.reset_for_tests()
    db = AsyncMock()
    out = await rag.retrieve_titles(db, uuid.uuid4(), question="!!!")
    assert out == []
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# ChunkHit accepts source="title"
# ---------------------------------------------------------------------------

def test_chunk_hit_accepts_title_source():
    h = rag.ChunkHit(
        chunk_id=None,
        episode_id=uuid.uuid4(),
        episode_title="Ft. 馬世芳",
        start_time=0.0,
        end_time=0.0,
        text="Ft. 馬世芳",
        source="title",
        rrf_score=0.1,
    )
    assert h.source == "title"
    assert h.chunk_id is None


# ---------------------------------------------------------------------------
# retrieve_hybrid merges three pools, fixture: title-only / desc-only /
# chunk-only matches sorted by weighted RRF score
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrieve_hybrid_merges_three_pools_by_rrf_score(monkeypatch):
    """Title / desc / chunk hits join the same ranking and sort by rrf_score.

    Build one fixture hit per pool with deliberately ordered RRF scores so
    the assertion does not depend on weight math — only that the merge
    function respects rrf_score ordering AND title hits (chunk_id=None)
    survive the dedupe set.
    """
    show_id = uuid.uuid4()
    ep_chunk = uuid.uuid4()
    ep_desc = uuid.uuid4()
    ep_title = uuid.uuid4()
    chunk_id_t = uuid.uuid4()
    chunk_id_d = uuid.uuid4()

    chunk_hit = rag.ChunkHit(
        chunk_id=chunk_id_t,
        episode_id=ep_chunk,
        episode_title="chunk ep",
        start_time=10.0,
        end_time=20.0,
        text="chunk text",
        source="transcript",
        rrf_score=0.030,
    )
    desc_hit = rag.ChunkHit(
        chunk_id=chunk_id_d,
        episode_id=ep_desc,
        episode_title="desc ep",
        start_time=0.0,
        end_time=0.0,
        text="desc text",
        source="description",
        rrf_score=0.020,
    )
    title_hit = rag.ChunkHit(
        chunk_id=None,
        episode_id=ep_title,
        episode_title="title ep",
        start_time=0.0,
        end_time=0.0,
        text="title ep",
        source="title",
        rrf_score=0.015,
    )

    async def fake_retrieve(*args, **kwargs):
        return [chunk_hit]

    async def fake_retrieve_descriptions(*args, **kwargs):
        return [desc_hit]

    async def fake_retrieve_titles(*args, **kwargs):
        return [title_hit]

    # retrieve_hybrid lives in rag_retrieval and calls retrieve/_descriptions/
    # _titles within its own module namespace, so patch them there (the rag
    # facade re-export is a separate binding that the internal calls bypass).
    monkeypatch.setattr(rag_retrieval, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag_retrieval, "retrieve_descriptions", fake_retrieve_descriptions)
    monkeypatch.setattr(rag_retrieval, "retrieve_titles", fake_retrieve_titles)

    db = AsyncMock()
    # query_embedding shape: rag._validate_query_dim is bypassed because we
    # patched the three retrieve_* functions.
    out = await rag.retrieve_hybrid(
        db, show_id, query_embedding=[0.0] * 1536, question="anything", k=8
    )

    # All three pools represented, sorted descending by rrf_score.
    sources = [h.source for h in out]
    assert "transcript" in sources
    assert "description" in sources
    assert "title" in sources
    assert sources[0] == "transcript"  # 0.030 > 0.020 > 0.015
    assert sources.index("description") < sources.index("title")
