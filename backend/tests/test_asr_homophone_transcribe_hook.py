"""Integration test: LLM homophone detection (layer 1) wired into _run.

Spec: transcription-pipeline → "LLM homophone detection precedes dictionary
correction". Drives `_run` with mocked external I/O against the real local
Postgres and asserts:
- both the LLM-detected correction AND the dictionary correction appear in the
  persisted segments, transcript content, and chunks;
- the LLM pair is persisted as a pending, disabled, show-scoped llm candidate;
- a detection failure is fail-open (transcription still completes with the
  dictionary correction only).
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
    """One segment + full text containing BOTH an LLM homophone target (世韻 =
    世運) and a known dictionary typo (咪有企 = 滅火器)."""
    text = "今天聊世韻會也聊咪有企"
    seg = SimpleNamespace(start=0.0, end=3.0, text=text)
    return SimpleNamespace(segments=[seg], text=text, language="zh")


def _fake_cfg(step_key: str):
    from app.services.ai_step_resolver import StepConfig

    return StepConfig(
        step_key=step_key,
        step_type=step_key,
        base_url="https://x",
        api_key="sk-fake",
        model="fake-model",
        extra_config={"prompt": "p"},
    )


@pytest_asyncio.fixture
async def seeded_episode(db_session):
    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.episode import Episode
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    show = Show(
        title=f"pytest-hphook-{suffix}",
        rss_url=f"https://e.com/{suffix}.rss",
        language="zh",
    )
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    ep = Episode(
        show_id=show.id,
        guid=f"pytest-hphook-{suffix}-ep",
        title=f"pytest-hphook-{suffix} EP1",
        audio_url=f"https://e.com/{suffix}.mp3",
        audio_storage_key=f"fake/{suffix}.mp3",
        # RAGEC candidate: 世運 is a known entity so the LLM's 世韻→世運 survives
        # the grounding filter.
        guests=["世運"],
    )
    # approved dictionary rule (second layer)
    rule = AsrCorrectionTerm(
        wrong="咪有企",
        correct="滅火器",
        scope="show",
        show_id=show.id,
        enabled=True,
        source="manual",
        status="approved",
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
    # detect_homophones resolves its own get_step_config (imported into the
    # asr_homophone module). Stub it so the detector builds a client without
    # needing a real api_key in the local DB; _call_llm is stubbed per-test.
    monkeypatch.setattr(
        tasks.asr_homophone,
        "get_step_config",
        AsyncMock(side_effect=lambda s, k: _fake_cfg(k)),
    )


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


async def test_both_layers_applied_and_candidate_persisted(
    db_session, seeded_episode, monkeypatch
):
    from app.workers import tasks

    _patch_run_externals(monkeypatch)
    # LLM (layer 1) returns the homophone pair 世韻→世運.
    monkeypatch.setattr(
        tasks.asr_homophone,
        "_call_llm",
        lambda client, **kw: '```json\n[{"wrong": "世韻", "correct": "世運"}]\n```',
    )

    result = await tasks._run(seeded_episode["episode_id"])
    assert result["status"] == "completed"

    tr, segs, chunks = await _load(db_session, seeded_episode["ep_uuid"])
    # both corrections present, both originals gone
    for blob in [tr.content] + [s.text for s in segs] + [c.text for c in chunks]:
        assert "世運" in blob and "世韻" not in blob, blob
        assert "滅火器" in blob and "咪有企" not in blob, blob

    # LLM pair persisted as a pending, disabled, show-scoped llm candidate
    from app.models.asr_correction_term import AsrCorrectionTerm

    cand = (
        await db_session.execute(
            select(AsrCorrectionTerm).where(
                AsrCorrectionTerm.show_id == seeded_episode["show_id"],
                AsrCorrectionTerm.wrong == "世韻",
            )
        )
    ).scalar_one()
    assert cand.correct == "世運"
    assert cand.source == "llm"
    assert cand.status == "pending"
    assert cand.enabled is False
    assert cand.scope == "show"


async def test_detection_failure_falls_back_to_dictionary_only(
    db_session, seeded_episode, monkeypatch
):
    from app.workers import tasks

    _patch_run_externals(monkeypatch)

    # LLM call raises → detect_homophones fail-open returns [] → layer 1 no-op.
    def _boom(client, **kw):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(tasks.asr_homophone, "_call_llm", _boom)

    result = await tasks._run(seeded_episode["episode_id"])
    assert result["status"] == "completed"

    tr, segs, _chunks = await _load(db_session, seeded_episode["ep_uuid"])
    # dictionary correction still applied
    assert "滅火器" in tr.content and "咪有企" not in tr.content
    # layer-1 target untouched (no LLM correction), no candidate persisted
    assert "世韻" in tr.content
    assert segs and any("世韻" in s.text for s in segs)

    from app.models.asr_correction_term import AsrCorrectionTerm

    cand = (
        await db_session.execute(
            select(AsrCorrectionTerm).where(
                AsrCorrectionTerm.show_id == seeded_episode["show_id"],
                AsrCorrectionTerm.wrong == "世韻",
            )
        )
    ).scalar_one_or_none()
    assert cand is None, "no candidate should be persisted on detection failure"
