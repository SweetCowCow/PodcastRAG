"""Tests for ASR correction backfill.

Spec: asr-correction-dictionary → Requirements
"Backfill recomputes only affected chunks" +
"Backfill runs as a resumable idempotent background task".

Seeds a transcript whose chunks are produced by the real `build_chunks`, then
drives `backfill_corrections` with a mocked embedding call against real
Postgres and asserts: dry-run writes nothing but reports counts/cost; a real
run rewrites only the affected chunk and re-runs are idempotent.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services import asr_correction
from tests.conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no local Postgres"
)


def _fake_embedding_cfg():
    from app.services.ai_step_resolver import StepConfig

    return StepConfig(
        step_key="embedding",
        step_type="embedding",
        base_url="https://x",
        api_key="sk-fake",
        model="fake",
        extra_config={},
    )


@pytest_asyncio.fixture
async def seeded_transcript(db_session):
    """Seed show + episode + transcript + 12 segments (seg0 has the typo) +
    chunks produced by the real build_chunks. Cleans up afterwards."""
    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.episode import Episode
    from app.models.show import Show
    from app.models.transcript import Transcript, TranscriptStatus
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment
    from app.services.chunking import build_chunks

    suffix = uuid.uuid4().hex[:6]
    show = Show(title=f"pytest-bf-{suffix}", rss_url=f"https://e.com/{suffix}.rss")
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    ep = Episode(
        show_id=show.id,
        guid=f"pytest-bf-{suffix}-ep",
        title=f"pytest-bf-{suffix} EP1",
        audio_url=f"https://e.com/{suffix}.mp3",
    )
    db_session.add(ep)
    await db_session.commit()
    await db_session.refresh(ep)

    tr = Transcript(episode_id=ep.id, status=TranscriptStatus.completed)
    db_session.add(tr)
    await db_session.commit()
    await db_session.refresh(tr)

    # 12 segments, 3s each, no large gaps → build_chunks makes 2 chunks
    # (first middle = 10 segs at MAX, second = remaining 2). seg0 has the typo.
    seg_rows = []
    for i in range(12):
        text = "今天聊咪有企的歌" if i == 0 else f"普通內容第{i}段這裡有一些字"
        seg = TranscriptSegment(
            transcript_id=tr.id,
            start_time=float(i * 3),
            end_time=float(i * 3 + 2),
            text=text,
        )
        seg_rows.append(seg)
    db_session.add_all(seg_rows)
    await db_session.commit()
    for s in seg_rows:
        await db_session.refresh(s)

    drafts = build_chunks(seg_rows)
    for idx, d in enumerate(drafts):
        db_session.add(
            TranscriptChunk(
                transcript_id=tr.id,
                chunk_index=idx,
                start_time=d.start_time,
                end_time=d.end_time,
                text=d.text,
                segment_ids=d.segment_ids,
            )
        )
    rule = AsrCorrectionTerm(
        wrong="咪有企", correct="滅火器", scope="show", show_id=show.id, enabled=True
    )
    db_session.add(rule)
    await db_session.commit()

    yield {"show_id": show.id, "transcript_id": tr.id, "n_chunks": len(drafts)}

    from sqlalchemy import delete

    await db_session.execute(
        delete(TranscriptChunk).where(TranscriptChunk.transcript_id == tr.id)
    )
    await db_session.execute(
        delete(TranscriptSegment).where(TranscriptSegment.transcript_id == tr.id)
    )
    await db_session.execute(delete(Transcript).where(Transcript.id == tr.id))
    await db_session.execute(
        delete(AsrCorrectionTerm).where(AsrCorrectionTerm.show_id == show.id)
    )
    await db_session.execute(delete(Episode).where(Episode.id == ep.id))
    await db_session.execute(delete(Show).where(Show.id == show.id))
    await db_session.commit()


async def _chunks(db_session, transcript_id):
    from app.models.transcript_chunk import TranscriptChunk

    return (
        (
            await db_session.execute(
                select(TranscriptChunk)
                .where(TranscriptChunk.transcript_id == transcript_id)
                .order_by(TranscriptChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )


async def test_dry_run_reports_counts_and_writes_nothing(
    db_session, seeded_transcript
):
    tid = seeded_transcript["transcript_id"]
    before = [c.text for c in await _chunks(db_session, tid)]

    report = await asr_correction.backfill_corrections(
        db_session, show_id=seeded_transcript["show_id"], dry_run=True
    )

    assert report.dry_run is True
    assert report.affected_segments >= 1
    assert report.affected_chunks >= 1
    assert report.estimated_cost_usd > 0
    # nothing written
    after = [c.text for c in await _chunks(db_session, tid)]
    assert before == after
    assert any("咪有企" in t for t in after), "dry-run must not correct the data"


async def test_real_run_recomputes_only_affected_chunk(
    db_session, seeded_transcript, monkeypatch
):
    tid = seeded_transcript["transcript_id"]

    def fake_embed(texts, cfg):
        return ([[0.1] * 1536 for _ in texts], [[0.2] * 3072 for _ in texts])

    monkeypatch.setattr(
        "app.services.embedding.embed_texts_dual", fake_embed
    )
    monkeypatch.setattr(
        "app.services.tokenizer.load_dictionary", AsyncMock(return_value=0)
    )

    report = await asr_correction.backfill_corrections(
        db_session,
        show_id=seeded_transcript["show_id"],
        dry_run=False,
        embedding_cfg=_fake_embedding_cfg(),
    )
    assert report.affected_chunks >= 1
    assert report.failed_chunk_ids == []

    chunks = await _chunks(db_session, tid)
    # affected chunk now corrected; no chunk retains the typo anywhere
    assert all("咪有企" not in c.text for c in chunks)
    assert any("滅火器" in c.text for c in chunks)
    # the corrected chunk got a fresh embedding + tsvector
    corrected = [c for c in chunks if "滅火器" in c.text]
    assert all(c.embedding_v2 is not None for c in corrected)
    assert all(c.text_tsvector is not None for c in corrected)


async def test_rerun_is_idempotent(db_session, seeded_transcript, monkeypatch):
    def fake_embed(texts, cfg):
        return ([[0.1] * 1536 for _ in texts], [[0.2] * 3072 for _ in texts])

    monkeypatch.setattr("app.services.embedding.embed_texts_dual", fake_embed)
    monkeypatch.setattr(
        "app.services.tokenizer.load_dictionary", AsyncMock(return_value=0)
    )
    cfg = _fake_embedding_cfg()

    first = await asr_correction.backfill_corrections(
        db_session, show_id=seeded_transcript["show_id"], dry_run=False, embedding_cfg=cfg
    )
    assert first.affected_chunks >= 1

    second = await asr_correction.backfill_corrections(
        db_session, show_id=seeded_transcript["show_id"], dry_run=False, embedding_cfg=cfg
    )
    # already corrected → nothing left to do
    assert second.affected_chunks == 0
    assert second.affected_segments == 0


async def test_chunk_failure_is_isolated(
    db_session, seeded_transcript, monkeypatch
):
    """A per-chunk recompute failure is recorded and skipped, not raised —
    the task must not abort the whole batch."""

    def fake_embed(texts, cfg):
        return ([[0.1] * 1536 for _ in texts], [[0.2] * 3072 for _ in texts])

    def _boom(_text):
        raise RuntimeError("tokenizer boom")

    monkeypatch.setattr("app.services.embedding.embed_texts_dual", fake_embed)
    monkeypatch.setattr(
        "app.services.tokenizer.load_dictionary", AsyncMock(return_value=0)
    )
    monkeypatch.setattr("app.services.tokenizer.tokenize", _boom)

    # Must NOT raise — failure is isolated and recorded.
    report = await asr_correction.backfill_corrections(
        db_session,
        show_id=seeded_transcript["show_id"],
        dry_run=False,
        embedding_cfg=_fake_embedding_cfg(),
    )
    assert len(report.failed_chunk_ids) >= 1


# ─── EQ2d: original snapshot + content sync + restore ──────────────────


def _patch_embed(monkeypatch):
    def fake_embed(texts, cfg):
        return ([[0.1] * 1536 for _ in texts], [[0.2] * 3072 for _ in texts])

    monkeypatch.setattr("app.services.embedding.embed_texts_dual", fake_embed)
    monkeypatch.setattr(
        "app.services.tokenizer.load_dictionary", AsyncMock(return_value=0)
    )


async def _get_tr(db_session, tid):
    from app.models.transcript import Transcript

    return await db_session.get(Transcript, tid)


async def _seg0(db_session, tid):
    from app.models.transcript_segment import TranscriptSegment

    return (
        await db_session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == tid)
            .order_by(TranscriptSegment.start_time)
        )
    ).scalars().first()


async def test_backfill_snapshots_original_and_syncs_content(
    db_session, seeded_transcript, monkeypatch
):
    _patch_embed(monkeypatch)
    tid = seeded_transcript["transcript_id"]
    tr = await _get_tr(db_session, tid)
    tr.content = "開頭 咪有企 結尾"
    await db_session.commit()

    await asr_correction.backfill_corrections(
        db_session, show_id=seeded_transcript["show_id"], dry_run=False,
        embedding_cfg=_fake_embedding_cfg(),
    )

    seg0 = await _seg0(db_session, tid)
    tr = await _get_tr(db_session, tid)
    assert seg0.original_text == "今天聊咪有企的歌", "pre-correction segment text snapshotted"
    assert "滅火器" in seg0.text and "咪有企" not in seg0.text
    assert tr.original_content == "開頭 咪有企 結尾", "pre-correction content snapshotted"
    assert tr.content == "開頭 滅火器 結尾", "content synced to corrected"

    # Re-run must NOT overwrite the original snapshot.
    await asr_correction.backfill_corrections(
        db_session, show_id=seeded_transcript["show_id"], dry_run=False,
        embedding_cfg=_fake_embedding_cfg(),
    )
    seg0 = await _seg0(db_session, tid)
    assert seg0.original_text == "今天聊咪有企的歌", "snapshot not overwritten on re-run"


async def test_backfill_force_content_resync_when_segments_already_corrected(
    db_session, seeded_transcript, monkeypatch
):
    """task 2.3: segments already corrected (no-op) but content stale → content
    must still be synced."""
    _patch_embed(monkeypatch)
    tid = seeded_transcript["transcript_id"]
    # Simulate the pre-EQ2d state: segment already corrected, content still wrong.
    seg0 = await _seg0(db_session, tid)
    seg0.text = "今天聊滅火器的歌"
    tr = await _get_tr(db_session, tid)
    tr.content = "開頭 咪有企 結尾"
    await db_session.commit()

    report = await asr_correction.backfill_corrections(
        db_session, show_id=seeded_transcript["show_id"], dry_run=False,
        embedding_cfg=_fake_embedding_cfg(),
    )
    tr = await _get_tr(db_session, tid)
    assert report.affected_segments == 0, "segments already correct → no segment work"
    assert tr.content == "開頭 滅火器 結尾", "content force-synced despite no segment change"
    assert tr.original_content == "開頭 咪有企 結尾", "content snapshot captured"


async def test_restore_reverts_and_clears_snapshot(
    db_session, seeded_transcript, monkeypatch
):
    _patch_embed(monkeypatch)
    tid = seeded_transcript["transcript_id"]
    tr = await _get_tr(db_session, tid)
    tr.content = "開頭 咪有企 結尾"
    await db_session.commit()
    episode_id = tr.episode_id

    # correct, then restore
    await asr_correction.backfill_corrections(
        db_session, show_id=seeded_transcript["show_id"], dry_run=False,
        embedding_cfg=_fake_embedding_cfg(),
    )
    report = await asr_correction.restore_episode(
        db_session, episode_id, embedding_cfg=_fake_embedding_cfg()
    )

    assert report.affected_segments >= 1
    seg0 = await _seg0(db_session, tid)
    tr = await _get_tr(db_session, tid)
    assert seg0.text == "今天聊咪有企的歌", "segment reverted to original"
    assert seg0.original_text is None, "snapshot cleared after restore"
    assert tr.content == "開頭 咪有企 結尾", "content reverted to original"
    assert tr.original_content is None, "content snapshot cleared after restore"
    chunks = await _chunks(db_session, tid)
    assert any("咪有企" in c.text for c in chunks), "chunks recomputed to original"


async def test_restore_noop_when_no_snapshot(
    db_session, seeded_transcript, monkeypatch
):
    _patch_embed(monkeypatch)
    tid = seeded_transcript["transcript_id"]
    tr = await _get_tr(db_session, tid)
    episode_id = tr.episode_id  # never corrected → no original_text anywhere

    report = await asr_correction.restore_episode(
        db_session, episode_id, embedding_cfg=_fake_embedding_cfg()
    )
    assert report.affected_segments == 0
