import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from app.models.transcript_segment import TranscriptSegment

MAX_SEGMENTS_PER_CHUNK = 5
MAX_CHUNK_DURATION_SECONDS = 60.0


@dataclass
class ChunkDraft:
    start_time: float
    end_time: float
    text: str
    segment_ids: list[uuid.UUID]


def build_chunks(segments: Iterable[TranscriptSegment]) -> list[ChunkDraft]:
    """Aggregate Whisper segments into chunks of 3–5 segments or up to 60 seconds."""
    drafts: list[ChunkDraft] = []
    current: list[TranscriptSegment] = []

    for seg in segments:
        current.append(seg)
        duration = current[-1].end_time - current[0].start_time
        if len(current) >= MAX_SEGMENTS_PER_CHUNK or duration >= MAX_CHUNK_DURATION_SECONDS:
            drafts.append(_build(current))
            current = []

    if current:
        drafts.append(_build(current))

    return drafts


def _build(segments: list[TranscriptSegment]) -> ChunkDraft:
    return ChunkDraft(
        start_time=segments[0].start_time,
        end_time=segments[-1].end_time,
        text=" ".join(s.text for s in segments),
        segment_ids=[s.id for s in segments],
    )
