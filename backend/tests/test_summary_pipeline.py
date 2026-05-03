"""Unit tests for summary_pipeline.chunk_segments — pure function."""

import tiktoken

from app.services.summary_pipeline import (
    CHUNK_TOKEN_LIMIT,
    SegmentInput,
    chunk_segments,
)


def _seg(text: str, start: float = 0.0) -> SegmentInput:
    return SegmentInput(text=text, start_time=start)


def test_empty_segments_returns_empty():
    assert chunk_segments([]) == []


def test_single_short_segment_one_chunk():
    chunks = chunk_segments([_seg("這是一段短話")])
    assert chunks == ["這是一段短話"]


def test_skips_blank_segments():
    chunks = chunk_segments(
        [_seg("first"), _seg("   "), _seg(""), _seg("second")]
    )
    assert chunks == ["first\nsecond"]


def test_does_not_split_mid_segment():
    """A segment that itself exceeds the token budget stays whole in its
    chunk — the algorithm is segment-aligned by contract."""
    enc = tiktoken.get_encoding("cl100k_base")
    big = "word " * 5000  # ~5000 tokens
    huge = "huge " * 13000  # > token_limit
    chunks = chunk_segments([_seg(big), _seg(huge)], token_limit=CHUNK_TOKEN_LIMIT)
    # huge segment is large enough on its own to exceed the budget; it should
    # land in a chunk by itself rather than be sliced apart.
    assert any(huge.strip() in c for c in chunks)
    # The huge segment must appear as ONE contiguous piece, not split across
    # chunks.
    matches = [c for c in chunks if huge.strip() in c]
    assert len(matches) == 1


def test_multiple_small_segments_pack_into_one_chunk():
    segs = [_seg(f"段{i} 這裡是一些文字內容") for i in range(20)]
    chunks = chunk_segments(segs)
    assert len(chunks) == 1


def test_segments_split_at_budget_boundary():
    """When accumulated tokens cross the limit, the next segment opens a
    new chunk — earlier ones stay in the previous chunk intact."""
    enc = tiktoken.get_encoding("cl100k_base")
    # Build segments so first 3 just fit under 100-token limit, 4th tips it.
    s1 = "alpha " * 30  # ~30 tokens
    s2 = "beta " * 30
    s3 = "gamma " * 30
    s4 = "delta " * 30
    chunks = chunk_segments(
        [_seg(s1), _seg(s2), _seg(s3), _seg(s4)], token_limit=100
    )
    assert len(chunks) >= 2
    # First chunk has s1 and s2, but not s4.
    assert s1.strip() in chunks[0]
    assert s4.strip() not in chunks[0]
    # s4 lands in some later chunk.
    assert any(s4.strip() in c for c in chunks[1:])


def test_last_chunk_preserved_even_if_small():
    """A tiny trailing segment after a budget-closing chunk must survive."""
    s_big = "alpha " * 60  # forces a budget close at limit=80
    s_tail = "tail"
    chunks = chunk_segments(
        [_seg(s_big), _seg(s_big), _seg(s_tail)], token_limit=80
    )
    assert chunks[-1].endswith("tail")
    assert len(chunks) >= 2
