"""Service + unit tests for EQ2e F8 (asr-homophone-full-backfill).

Covers:
- `_map_backfill_status`: the fixed status shape mapping for all six states
  (PENDING / PROGRESS / SUCCESS / FAILURE / REVOKED / unknown). Spec:
  asr-correction-dictionary → "Backfill jobs report progress and are cancellable"
  (status query maps to a fixed shape; unknown does not error).
- `asr_correction.batch_restore`: reverting multiple snapshotted episodes. Spec:
  "Batch restore of episodes touched by rule application".
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.api.admin.asr_corrections import _map_backfill_status
from app.services import asr_correction
from tests.conftest import _postgres_reachable


# ─── _map_backfill_status: six-state mapping (no DB) ───────────────────


def test_map_status_progress():
    r = _map_backfill_status(
        SimpleNamespace(
            state="PROGRESS",
            info={"current": 4, "total": 10, "phase": "detect", "failed_chunk_ids": ["e1"]},
        )
    )
    assert r.state == "PROGRESS"
    assert (r.current, r.total) == (4, 10)
    assert r.phase == "detect"
    assert r.failed_chunk_ids == ["e1"]
    assert "4/10" in r.message


def test_map_status_pending():
    r = _map_backfill_status(SimpleNamespace(state="PENDING", info=None))
    assert r.state == "PENDING"


def test_map_status_success_reads_terminal_dict():
    r = _map_backfill_status(
        SimpleNamespace(
            state="SUCCESS",
            info={"affected_transcripts": 7, "failed_chunk_ids": ["c9"]},
        )
    )
    assert r.state == "SUCCESS"
    assert r.total == 7
    assert r.failed_chunk_ids == ["c9"]


def test_map_status_failure():
    r = _map_backfill_status(
        SimpleNamespace(state="FAILURE", info=RuntimeError("boom"))
    )
    assert r.state == "FAILURE"
    assert "boom" in r.message


def test_map_status_revoked():
    r = _map_backfill_status(SimpleNamespace(state="REVOKED", info=None))
    assert r.state == "REVOKED"


def test_map_status_unknown_does_not_raise():
    r = _map_backfill_status(SimpleNamespace(state="WAT", info=None))
    assert r.state == "UNKNOWN"
    # an object with no state at all must also map to UNKNOWN, not error
    r2 = _map_backfill_status(SimpleNamespace())
    assert r2.state == "UNKNOWN"


# ─── batch_restore: revert multiple snapshotted episodes (needs PG) ────

pg_only = pytest.mark.skipif(not _postgres_reachable(), reason="no local Postgres")


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
async def two_corrected_episodes(db_session, monkeypatch):
    """Seed a show + 2 episodes, each with a transcript + segments containing the
    typo + chunks, plus an enabled rule. Correct both via backfill so they carry
    snapshots. Yields show_id + episode_ids; cleans up afterwards."""
    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.episode import Episode
    from app.models.show import Show
    from app.models.transcript import Transcript, TranscriptStatus
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment
    from app.services.chunking import build_chunks

    def fake_embed(texts, cfg):
        return ([[0.1] * 1536 for _ in texts], [[0.2] * 3072 for _ in texts])

    monkeypatch.setattr("app.services.embedding.embed_texts_dual", fake_embed)
    monkeypatch.setattr(
        "app.services.tokenizer.load_dictionary", AsyncMock(return_value=0)
    )

    suffix = uuid.uuid4().hex[:6]
    show = Show(title=f"pytest-br-{suffix}", rss_url=f"https://e.com/{suffix}.rss")
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    ep_ids = []
    for k in range(2):
        ep = Episode(
            show_id=show.id,
            guid=f"pytest-br-{suffix}-ep{k}",
            title=f"pytest-br-{suffix} EP{k}",
            audio_url=f"https://e.com/{suffix}-{k}.mp3",
        )
        db_session.add(ep)
        await db_session.commit()
        await db_session.refresh(ep)
        tr = Transcript(
            episode_id=ep.id,
            status=TranscriptStatus.completed,
            content="開頭 咪有企 結尾",
        )
        db_session.add(tr)
        await db_session.commit()
        await db_session.refresh(tr)
        segs = []
        for i in range(12):
            text = "今天聊咪有企的歌" if i == 0 else f"普通內容第{i}段這裡有一些字"
            segs.append(
                TranscriptSegment(
                    transcript_id=tr.id,
                    start_time=float(i * 3),
                    end_time=float(i * 3 + 2),
                    text=text,
                )
            )
        db_session.add_all(segs)
        await db_session.commit()
        for s in segs:
            await db_session.refresh(s)
        for idx, d in enumerate(build_chunks(segs)):
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
        await db_session.commit()
        ep_ids.append(ep.id)

    rule = AsrCorrectionTerm(
        wrong="咪有企", correct="滅火器", scope="show", show_id=show.id, enabled=True,
        status="approved", source="manual",
    )
    db_session.add(rule)
    await db_session.commit()

    # Correct both episodes → snapshots written.
    await asr_correction.backfill_corrections(
        db_session, show_id=show.id, dry_run=False, embedding_cfg=_fake_embedding_cfg()
    )

    yield {"show_id": show.id, "episode_ids": ep_ids}

    await db_session.execute(
        delete(AsrCorrectionTerm).where(AsrCorrectionTerm.show_id == show.id)
    )
    for ep_id in ep_ids:
        tr = (
            await db_session.execute(
                select(Transcript.id).where(Transcript.episode_id == ep_id)
            )
        ).scalar_one()
        await db_session.execute(
            delete(TranscriptChunk).where(TranscriptChunk.transcript_id == tr)
        )
        await db_session.execute(
            delete(TranscriptSegment).where(TranscriptSegment.transcript_id == tr)
        )
        await db_session.execute(delete(Transcript).where(Transcript.id == tr))
        await db_session.execute(delete(Episode).where(Episode.id == ep_id))
    await db_session.execute(delete(Show).where(Show.id == show.id))
    await db_session.commit()


@pg_only
async def test_batch_restore_reverts_two_episodes(
    db_session, two_corrected_episodes
):
    from app.models.transcript import Transcript

    show_id = two_corrected_episodes["show_id"]

    report = await asr_correction.batch_restore(
        db_session, show_id=show_id, embedding_cfg=_fake_embedding_cfg()
    )

    assert report.affected_transcripts == 2, "both snapshotted episodes reverted"
    # both transcripts back to original ASR text, snapshots cleared
    for ep_id in two_corrected_episodes["episode_ids"]:
        tr = (
            await db_session.execute(
                select(Transcript).where(Transcript.episode_id == ep_id)
            )
        ).scalar_one()
        await db_session.refresh(tr)
        assert tr.content == "開頭 咪有企 結尾"
        assert tr.original_content is None
