"""Smoke test for rebuild_chunks.

The full flow needs OpenAI + DB; this test seeds a small fixture transcript,
stubs `embed_texts` to a deterministic vector, and asserts that the rebuild
deletes old chunks and writes new ones with non-null text_tsvector.
"""
from __future__ import annotations

import secrets
import uuid

import pytest

from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@db_required
@pytest.mark.asyncio
async def test_rebuild_replaces_chunks_and_populates_tsvector(
    db_session, monkeypatch
):
    from sqlalchemy import select

    from app.models.episode import Episode
    from app.models.show import Show
    from app.models.transcript import Transcript, TranscriptStatus
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment
    from scripts import rebuild_chunks

    suffix = secrets.token_hex(4)
    show = Show(
        title=f"pytest-show-{suffix}",
        rss_url=f"https://example.test/{suffix}.rss",
        language="zh",
    )
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    episode = Episode(
        show_id=show.id,
        title=f"pytest-ep-{suffix}",
        audio_url=f"https://example.test/{suffix}.mp3",
        guid=f"pytest-{suffix}",
    )
    db_session.add(episode)
    await db_session.commit()
    await db_session.refresh(episode)

    transcript = Transcript(
        episode_id=episode.id, status=TranscriptStatus.completed
    )
    db_session.add(transcript)
    await db_session.commit()
    await db_session.refresh(transcript)

    # Seed 12 contiguous segments — produces at least one chunk under the new
    # algorithm (10 segs × 3s closes at max-segments).
    for i in range(12):
        db_session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                start_time=i * 3.0,
                end_time=(i + 1) * 3.0,
                text=f"segment {i} 中文內容",
            )
        )

    # Pre-existing chunk that should be deleted.
    db_session.add(
        TranscriptChunk(
            transcript_id=transcript.id,
            chunk_index=99,
            start_time=0.0,
            end_time=10.0,
            text="old chunk",
            segment_ids=[uuid.uuid4()],
        )
    )
    await db_session.commit()

    # Stub embed_texts to deterministic vector.
    def fake_embed(texts, _cfg):
        return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr(rebuild_chunks, "embed_texts", fake_embed)

    # Stub get_step_config: rebuild needs an embedding step config.
    class _Cfg:
        base_url = "https://test"
        api_key = "x"
        model = "text-embedding-3-small"

    async def fake_get(_s, _k):
        return _Cfg()

    monkeypatch.setattr(rebuild_chunks, "get_step_config", fake_get)

    totals = await rebuild_chunks.run(all_=False, transcript_id=transcript.id)
    assert totals.errors == 0
    assert totals.chunks_inserted >= 1

    rows = (
        await db_session.execute(
            select(TranscriptChunk).where(
                TranscriptChunk.transcript_id == transcript.id
            )
        )
    ).scalars().all()
    assert len(rows) == totals.chunks_inserted
    assert all(r.text_tsvector is not None for r in rows), (
        "every new chunk should have text_tsvector populated"
    )
    assert all(r.embedding is not None for r in rows), (
        "every new chunk should have embedding populated"
    )
    # The pre-existing old chunk (chunk_index=99) should be gone.
    assert all(r.chunk_index < 99 for r in rows)
