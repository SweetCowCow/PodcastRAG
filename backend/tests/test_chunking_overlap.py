"""Chunk builder unit tests covering overlap + closing rules."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.services.chunking import build_chunks


@dataclass
class FakeSegment:
    id: uuid.UUID
    start_time: float
    end_time: float
    text: str


def _seg(start: float, end: float, text: str) -> FakeSegment:
    return FakeSegment(id=uuid.uuid4(), start_time=start, end_time=end, text=text)


def _make_dense(n: int, seg_dur: float = 4.0, gap: float = 0.0) -> list[FakeSegment]:
    """n segments back-to-back with optional uniform gap."""
    out = []
    t = 0.0
    for i in range(n):
        out.append(_seg(t, t + seg_dur, f"seg{i}"))
        t = t + seg_dur + gap
    return out


def test_close_at_max_segments_when_short():
    # 10 dense ~3s segments → 30s total → max-segments hits before max-duration
    segs = _make_dense(10, seg_dur=3.0)
    chunks = build_chunks(segs)
    assert len(chunks) == 1
    assert chunks[0].segment_ids == [s.id for s in segs[:10]]


def test_close_at_max_duration_when_long_segments():
    # 7 dense 10s segments → middle hits 60s before 10 segments
    segs = _make_dense(7, seg_dur=10.0)
    chunks = build_chunks(segs)
    # the first chunk closes when middle reaches 60s.
    # 6 segments × 10s = 60s exactly → triggers max-duration check
    assert len(chunks[0].segment_ids) <= 7
    assert chunks[0].end_time - chunks[0].start_time >= 60.0


def test_close_at_natural_gap_after_min_conditions():
    # 5 short segments (~6s each = 30s), then a > 1.5s gap, then more
    segs = (
        _make_dense(5, seg_dur=6.0)
        + [_seg(30 + 2.0, 30 + 2.0 + 6.0, "after-gap-1")]
        + [_seg(38 + 0.0, 38 + 6.0, "after-gap-2")]
    )
    chunks = build_chunks(segs)
    assert chunks[0].segment_ids == [s.id for s in segs[:5]]


def test_overlap_text_includes_one_before_and_one_after():
    # Force closure at exactly 5 middle segments via a natural gap.
    middle = _make_dense(5, seg_dur=6.0)
    pre = [_seg(-6.0, 0.0, "pre")]
    middle_with_pre = pre + middle
    # add a > 1.5s gap then more segments to trigger gap-close on middle
    post1 = _seg(30 + 2.0, 30 + 2.0 + 4.0, "post1")
    post2 = _seg(36 + 2.0, 36 + 2.0 + 4.0, "post2")
    segs = middle_with_pre + [post1, post2]
    chunks = build_chunks(segs)

    first = chunks[0]
    # middle was indices 0..0 (just "pre") — no, actually the gap is *after* middle index 5
    # So the first chunk's middle should be indices 0-5 (6 segs total in middle)?
    # Recompute: gap is between middle[4] (index 5 in segs) and post1 (index 6) = 2.0s
    # So middle = segs[0..5]; pre overlap = none (chunk starts at index 0); post overlap = post1
    # text = pre + 5 middle + post1 = 7 pieces
    expected_text_pieces = [s.text for s in segs[: 6 + 1]]
    assert first.text.split() == [t for piece in expected_text_pieces for t in piece.split()]
    assert first.segment_ids == [s.id for s in segs[:6]]
    assert first.start_time == segs[0].start_time
    assert first.end_time == segs[5].end_time


def test_first_chunk_has_no_preceding_overlap():
    segs = _make_dense(12, seg_dur=3.0)
    chunks = build_chunks(segs)
    first = chunks[0]
    # First chunk's text should start with seg0
    assert first.text.startswith("seg0")


def test_last_chunk_has_no_trailing_overlap():
    # One chunk only: 10 segments × 3s = 30s, max-segments closes
    segs = _make_dense(10, seg_dur=3.0)
    chunks = build_chunks(segs)
    last = chunks[-1]
    # No trailing overlap because no segments remain after middle
    assert last.text.endswith("seg9")


def test_trailing_partial_flushed():
    # 12 segments × 3s = 36s; first chunk = 10 segs (30s), trailing 2 flushed
    segs = _make_dense(12, seg_dur=3.0)
    chunks = build_chunks(segs)
    assert len(chunks) == 2
    assert len(chunks[1].segment_ids) == 2


def test_empty_input_returns_empty():
    assert build_chunks([]) == []
