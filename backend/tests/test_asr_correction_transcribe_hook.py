"""Integration test: ASR correction applied inside the transcribe worker.

Spec: transcription-pipeline → Requirement "ASR correction applied before
chunking". Drives `_run` with mocked external I/O (storage / provider /
embedding / tokenizer / queue helpers) against the real local Postgres, and
asserts the typo is corrected at the source in segment text, transcript
content, AND the resulting chunks — plus that a correction-load failure is
fail-open (transcription still completes, segment keeps original text).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from tests.conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no local Postgres"
)


def _fake_result():
    """One segment + full text, both containing the typo 咪有企 (= 滅火器)."""
    seg = SimpleNamespace(start=0.0, end=3.0, text="今天聊咪有企的歌")
    return SimpleNamespace(segments=[seg], text="今天聊咪有企的歌", language="zh")


def _fake_cfg(step_key: str):
    from app.services.ai_step_resolver import StepConfig

    return StepConfig(
        step_key=step_key,
        step_type=step_key,
        base_url="https://x",
        api_key="sk-fake",
        model="fake-model",
        extra_config={},
    )


@pytest_asyncio.fixture
async def seeded_episode(db_session):
    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.episode import Episode
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    show = Show(
        title=f"pytest-asrhook-{suffix}",
        rss_url=f"https://e.com/{suffix}.rss",
        language="zh",
    )
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    ep = Episode(
        show_id=show.id,
        guid=f"pytest-asrhook-{suffix}-ep",
        title=f"pytest-asrhook-{suffix} EP1",
        audio_url=f"https://e.com/{suffix}.mp3",
        audio_storage_key=f"fake/{suffix}.mp3",
    )
    rule = AsrCorrectionTerm(
        wrong="咪有企", correct="滅火器", scope="show", show_id=show.id, enabled=True
    )
    db_session.add_all([ep, rule])
    await db_session.commit()
    await db_session.refresh(ep)

    yield {"episode_id": str(ep.id), "ep_uuid": ep.id, "show_id": show.id}

    from app.models.transcript import Transcript
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment

    tr = (
        await db_session.execute(
            select(Transcript).where(Transcript.episode_id == ep.id)
        )
    ).scalar_one_or_none()
    if tr is not None:
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


def _patch_run_externals(monkeypatch):
    """Patch every external I/O dependency of `_run` so it runs offline.
    Leaves `build_chunks` and the correction logic real."""
    from app.workers import tasks

    fake_provider = SimpleNamespace(
        transcribe=AsyncMock(return_value=_fake_result())
    )

    monkeypatch.setattr(tasks, "_is_queue_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(tasks, "_mark_queue_finished", AsyncMock())
    monkeypatch.setattr(tasks.storage, "download_to_temp", lambda key: "/tmp/fake.mp3")
    monkeypatch.setattr(
        tasks, "get_step_config", AsyncMock(side_effect=lambda s, k: _fake_cfg(k))
    )
    monkeypatch.setattr(tasks, "get_provider", lambda cfg: fake_provider)
    monkeypatch.setattr(
        tasks,
        "embed_texts_dual",
        lambda texts, cfg: (
            [[0.1] * 1536 for _ in texts],
            [[0.2] * 3072 for _ in texts],
        ),
    )
    monkeypatch.setattr(tasks.tokenizer, "load_dictionary", AsyncMock(return_value=0))
    monkeypatch.setattr(tasks.tokenizer, "tokenize", lambda t: list(t))


async def _load(db_session, ep_uuid):
    from app.models.transcript import Transcript
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment

    tr = (
        await db_session.execute(
            select(Transcript).where(Transcript.episode_id == ep_uuid)
        )
    ).scalar_one()
    segs = (
        (
            await db_session.execute(
                select(TranscriptSegment).where(
                    TranscriptSegment.transcript_id == tr.id
                )
            )
        )
        .scalars()
        .all()
    )
    chunks = (
        (
            await db_session.execute(
                select(TranscriptChunk).where(
                    TranscriptChunk.transcript_id == tr.id
                )
            )
        )
        .scalars()
        .all()
    )
    return tr, segs, chunks


async def test_new_transcript_corrected_at_source(
    db_session, seeded_episode, monkeypatch
):
    from app.workers import tasks

    _patch_run_externals(monkeypatch)
    result = await tasks._run(seeded_episode["episode_id"])
    assert result["status"] == "completed"

    tr, segs, chunks = await _load(db_session, seeded_episode["ep_uuid"])
    assert "滅火器" in tr.content and "咪有企" not in tr.content
    assert segs and all("咪有企" not in s.text for s in segs)
    assert any("滅火器" in s.text for s in segs)
    assert chunks and all("咪有企" not in c.text for c in chunks)
    assert any("滅火器" in c.text for c in chunks)


async def test_correction_failure_does_not_block_transcription(
    db_session, seeded_episode, monkeypatch
):
    from app.workers import tasks

    _patch_run_externals(monkeypatch)
    # load_rules raising must be fail-open: transcription completes, text uncorrected.
    monkeypatch.setattr(
        tasks.asr_correction,
        "load_rules",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    result = await tasks._run(seeded_episode["episode_id"])
    assert result["status"] == "completed"

    _tr, segs, _chunks = await _load(db_session, seeded_episode["ep_uuid"])
    assert segs and any("咪有企" in s.text for s in segs), (
        "fail-open: original (uncorrected) text must survive when correction fails"
    )
