"""Chunk builder with overlap context (R3.1 hybrid retrieval).

Each chunk has a "middle" region (5-10 segments / 30-60s) plus one preceding
and one trailing overlap segment for retrieval context. `segment_ids` and
`start_time/end_time` reflect the middle only — the overlap is text-only so
that "play from this time" UI affordances stay accurate.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from app.models.transcript_segment import TranscriptSegment

MIN_MIDDLE_SEGMENTS = 5
MAX_MIDDLE_SEGMENTS = 10
MIN_MIDDLE_DURATION_SECONDS = 30.0
MAX_MIDDLE_DURATION_SECONDS = 60.0
NATURAL_GAP_SECONDS = 1.5
OVERLAP_BEFORE = 1
OVERLAP_AFTER = 1


@dataclass
class ChunkDraft:
    start_time: float
    end_time: float
    text: str
    segment_ids: list[uuid.UUID]
    middle_start_idx: int
    middle_end_idx: int  # inclusive


def build_chunks(segments: Iterable[TranscriptSegment]) -> list[ChunkDraft]:
    """Aggregate Whisper segments into overlap-aware chunks.

    Closing rules for the middle region (any-of):
      (a) middle reaches MAX_MIDDLE_SEGMENTS
      (b) middle reaches MAX_MIDDLE_DURATION_SECONDS
      (c) min-conditions met AND next gap > NATURAL_GAP_SECONDS
      (d) end-of-input
    """
    seg_list = list(segments)
    drafts: list[ChunkDraft] = []
    if not seg_list:
        return drafts

    middle_start = 0
    while middle_start < len(seg_list):
        middle_end = middle_start
        while True:
            middle_count = middle_end - middle_start + 1
            duration = (
                seg_list[middle_end].end_time - seg_list[middle_start].start_time
            )

            if (
                middle_count >= MAX_MIDDLE_SEGMENTS
                or duration >= MAX_MIDDLE_DURATION_SECONDS
            ):
                break

            if middle_end + 1 >= len(seg_list):
                break

            next_gap = (
                seg_list[middle_end + 1].start_time - seg_list[middle_end].end_time
            )
            if (
                middle_count >= MIN_MIDDLE_SEGMENTS
                and duration >= MIN_MIDDLE_DURATION_SECONDS
                and next_gap > NATURAL_GAP_SECONDS
            ):
                break

            middle_end += 1

        drafts.append(_build(seg_list, middle_start, middle_end))
        middle_start = middle_end + 1

    return drafts


def _build(
    seg_list: list[TranscriptSegment], middle_start: int, middle_end: int
) -> ChunkDraft:
    """Build a chunk whose `text` includes overlap segments on each side."""
    text_start = max(0, middle_start - OVERLAP_BEFORE)
    text_end = min(len(seg_list) - 1, middle_end + OVERLAP_AFTER)

    text_pieces = [s.text for s in seg_list[text_start : text_end + 1]]
    return ChunkDraft(
        start_time=seg_list[middle_start].start_time,
        end_time=seg_list[middle_end].end_time,
        text=" ".join(t for t in text_pieces if t),
        segment_ids=[s.id for s in seg_list[middle_start : middle_end + 1]],
        middle_start_idx=middle_start,
        middle_end_idx=middle_end,
    )
