"""Tests for the LLM homophone detection service (EQ2b).

Spec: asr-homophone-detection → Requirements
- "LLM homophone detection produces word-level pairs"
- "Detection is fail-open"
- "Detected pairs persisted as pending candidates" + "Duplicate detection skipped"
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.services import asr_homophone
from app.services.asr_correction import CorrectionRule
from tests.conftest import _postgres_reachable


def _fake_client(content: str):
    """Build a fake OpenAI-style client whose chat completion returns `content`."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    resp = SimpleNamespace(choices=[choice])
    completions = SimpleNamespace(create=lambda **kw: resp)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


# ─── _strip_code_block / _parse_pairs: pure-function unit tests ────────


def test_parse_pairs_strips_markdown_code_block():
    raw = '```json\n[{"wrong": "世韻", "correct": "世運"}]\n```'
    pairs = asr_homophone._parse_pairs(raw)
    assert pairs == [CorrectionRule("世韻", "世運")]


def test_parse_pairs_plain_array():
    raw = '[{"wrong": "咪有企", "correct": "滅火器"}]'
    assert asr_homophone._parse_pairs(raw) == [CorrectionRule("咪有企", "滅火器")]


def test_parse_pairs_object_wrapper():
    raw = '{"pairs": [{"wrong": "杜忠祐", "correct": "杜宗祐"}]}'
    assert asr_homophone._parse_pairs(raw) == [CorrectionRule("杜忠祐", "杜宗祐")]


def test_parse_pairs_empty_and_noop_filtered():
    assert asr_homophone._parse_pairs("[]") == []
    # wrong == correct and empty wrong are dropped
    raw = '[{"wrong": "同", "correct": "同"}, {"wrong": "", "correct": "x"}]'
    assert asr_homophone._parse_pairs(raw) == []


# ─── detect_homophones: word-level pairs + empty + fail-open ───────────


async def test_detect_returns_word_level_pairs():
    client = _fake_client('```json\n[{"wrong": "世韻", "correct": "世運"}]\n```')
    pairs = await asr_homophone.detect_homophones(
        AsyncMock(),  # session unused when client/model/prompt injected
        "今天聊世韻會",
        client=client,
        model="fake-model",
        prompt="p",
    )
    assert pairs == [CorrectionRule("世韻", "世運")]


async def test_detect_no_homophone_returns_empty():
    client = _fake_client("[]")
    pairs = await asr_homophone.detect_homophones(
        AsyncMock(), "一切正常的句子", client=client, model="m", prompt="p"
    )
    assert pairs == []


async def test_detect_fail_open_on_llm_error():
    def _boom(**kw):
        raise RuntimeError("LLM down")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_boom))
    )
    pairs = await asr_homophone.detect_homophones(
        AsyncMock(), "今天聊世韻會", client=client, model="m", prompt="p"
    )
    assert pairs == [], "fail-open: LLM error must yield empty list, not raise"


async def test_detect_fail_open_on_bad_json():
    client = _fake_client("not json at all {{{")
    pairs = await asr_homophone.detect_homophones(
        AsyncMock(), "今天聊世韻會", client=client, model="m", prompt="p"
    )
    assert pairs == [], "fail-open: malformed JSON must yield empty list"


# ─── persist_candidates: pending candidates + dedup (real Postgres) ────


@pytest_asyncio.fixture
async def homophone_show(db_session):
    from sqlalchemy import delete

    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    show = Show(title=f"pytest-hp-{suffix}", rss_url=f"https://e.com/{suffix}.rss")
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    yield {"show_id": show.id, "suffix": suffix}

    await db_session.execute(
        delete(AsrCorrectionTerm).where(AsrCorrectionTerm.show_id == show.id)
    )
    await db_session.execute(delete(Show).where(Show.id == show.id))
    await db_session.commit()


@pytest.mark.skipif(not _postgres_reachable(), reason="no local Postgres")
async def test_persist_new_pairs_as_pending_candidates(db_session, homophone_show):
    from sqlalchemy import select

    from app.models.asr_correction_term import AsrCorrectionTerm

    sid = homophone_show["suffix"]
    show_id = homophone_show["show_id"]
    pairs = [CorrectionRule(f"錯A{sid}", "正A"), CorrectionRule(f"錯B{sid}", "正B")]

    inserted = await asr_homophone.persist_candidates(
        db_session, pairs, show_id=show_id
    )
    assert inserted == 2

    rows = (
        (
            await db_session.execute(
                select(AsrCorrectionTerm).where(
                    AsrCorrectionTerm.show_id == show_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    for r in rows:
        assert r.source == "llm"
        assert r.status == "pending"
        assert r.enabled is False
        assert r.scope == "show"


@pytest.mark.skipif(not _postgres_reachable(), reason="no local Postgres")
async def test_persist_skips_duplicate_any_status(db_session, homophone_show):
    from sqlalchemy import select

    from app.models.asr_correction_term import AsrCorrectionTerm

    sid = homophone_show["suffix"]
    show_id = homophone_show["show_id"]

    # Pre-seed: one approved rule and one rejected rule for this show.
    db_session.add_all(
        [
            AsrCorrectionTerm(
                wrong=f"已核{sid}",
                correct="approved",
                scope="show",
                show_id=show_id,
                enabled=True,
                source="manual",
                status="approved",
            ),
            AsrCorrectionTerm(
                wrong=f"已駁{sid}",
                correct="rejected",
                scope="show",
                show_id=show_id,
                enabled=False,
                source="llm",
                status="rejected",
            ),
        ]
    )
    await db_session.commit()

    # LLM re-detects both existing wrongs + one genuinely new one.
    pairs = [
        CorrectionRule(f"已核{sid}", "DIFFERENT"),  # collides w/ approved
        CorrectionRule(f"已駁{sid}", "DIFFERENT"),  # collides w/ rejected
        CorrectionRule(f"全新{sid}", "fresh"),  # new
    ]
    inserted = await asr_homophone.persist_candidates(
        db_session, pairs, show_id=show_id
    )
    assert inserted == 1, "only the genuinely new pair is inserted"

    rows = (
        (
            await db_session.execute(
                select(AsrCorrectionTerm).where(
                    AsrCorrectionTerm.show_id == show_id
                )
            )
        )
        .scalars()
        .all()
    )
    by_wrong = {r.wrong: r for r in rows}
    # existing statuses unchanged
    assert by_wrong[f"已核{sid}"].status == "approved"
    assert by_wrong[f"已核{sid}"].correct == "approved"
    assert by_wrong[f"已駁{sid}"].status == "rejected"
    assert by_wrong[f"已駁{sid}"].correct == "rejected"
    # new one is a pending candidate
    assert by_wrong[f"全新{sid}"].status == "pending"
    assert by_wrong[f"全新{sid}"].source == "llm"


# ─── estimate_detection_cost: dry-run, no LLM, no writes (real Postgres) ──


@pytest.mark.skipif(not _postgres_reachable(), reason="no local Postgres")
async def test_estimate_detection_cost_no_llm_no_writes(db_session, homophone_show):
    from sqlalchemy import func, select

    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.episode import Episode
    from app.models.transcript import Transcript

    show_id = homophone_show["show_id"]
    sid = homophone_show["suffix"]

    ep = Episode(
        show_id=show_id,
        guid=f"hp-cost-{sid}",
        title=f"hp-cost-{sid}",
        audio_url=f"https://e.com/{sid}c.mp3",
    )
    db_session.add(ep)
    await db_session.commit()
    await db_session.refresh(ep)
    content = "字" * 100
    db_session.add(Transcript(episode_id=ep.id, content=content))
    await db_session.commit()

    before = (
        await db_session.execute(
            select(func.count()).select_from(AsrCorrectionTerm)
        )
    ).scalar_one()

    # _call_llm must never be invoked by a dry-run.
    def _fail(*a, **k):
        raise AssertionError("dry-run must not call the LLM")

    monkey_orig = asr_homophone._call_llm
    asr_homophone._call_llm = _fail
    try:
        est = await asr_homophone.estimate_detection_cost(db_session, [ep.id])
    finally:
        asr_homophone._call_llm = monkey_orig

    assert est.episode_count == 1
    assert est.total_chars == 100
    assert est.estimated_input_tokens == 100 + asr_homophone._EST_PROMPT_OVERHEAD_TOKENS
    assert est.estimated_cost_usd > 0.0

    # no candidate rows written, no transcript mutated
    after = (
        await db_session.execute(
            select(func.count()).select_from(AsrCorrectionTerm)
        )
    ).scalar_one()
    assert after == before
    tr = (
        await db_session.execute(
            select(Transcript).where(Transcript.episode_id == ep.id)
        )
    ).scalar_one()
    assert tr.content == content

    from sqlalchemy import delete

    await db_session.execute(delete(Transcript).where(Transcript.episode_id == ep.id))
    await db_session.execute(delete(Episode).where(Episode.id == ep.id))
    await db_session.commit()
