"""Tests for the ASR correction service.

Spec: asr-correction-dictionary → Requirements
"Literal whole-term matching" + "Rule scope resolution by show".
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.services.asr_correction import (
    CorrectionRule,
    apply_corrections,
    load_rules,
)
from tests.conftest import _postgres_reachable


# ─── apply_corrections: pure-function unit tests ──────────────────────


def test_literal_replacement():
    rules = [CorrectionRule("咪有企", "滅火器")]
    assert apply_corrections("今天聊咪有企的歌", rules) == "今天聊滅火器的歌"


def test_regex_metacharacters_treated_literally():
    rules = [CorrectionRule("a.b", "X")]
    # the dot is literal: 'acb' must NOT match
    assert apply_corrections("acb", rules) == "acb"
    # the literal 'a.b' does match
    assert apply_corrections("a.b", rules) == "X"


@pytest.mark.parametrize(
    "wrong,correct,text,expected",
    [
        ("咪有企", "滅火器", "今天聊咪有企的歌", "今天聊滅火器的歌"),
        ("世韻", "世運", "世韻會開幕", "世運會開幕"),
        ("a.b", "X", "acb", "acb"),
    ],
)
def test_spec_example_table(wrong, correct, text, expected):
    assert apply_corrections(text, [CorrectionRule(wrong, correct)]) == expected


def test_multiple_rules_apply_longest_wrong_first():
    # "世運" is a substring of "世運會"; longest-first ordering must ensure the
    # longer rule wins so the shorter rule cannot pre-empt and corrupt it.
    rules = [
        CorrectionRule("世運", "世界運動會"),
        CorrectionRule("世運會", "WG"),
    ]
    assert apply_corrections("看世運會轉播", rules) == "看WG轉播"


def test_every_occurrence_replaced():
    rules = [CorrectionRule("咪有企", "滅火器")]
    assert apply_corrections("咪有企又咪有企", rules) == "滅火器又滅火器"


def test_empty_text_or_no_rules_is_noop():
    assert apply_corrections("", [CorrectionRule("a", "b")]) == ""
    assert apply_corrections("hello", []) == "hello"


# ─── load_rules: real-Postgres tests ──────────────────────────────────


@pytest_asyncio.fixture
async def rules_fixture(db_session):
    """Seed two shows and four rules (global enabled, show-S enabled,
    other-show enabled, global disabled). Cleans up by `wrong` suffix."""
    from sqlalchemy import delete

    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    show_s = Show(title=f"pytest-asr-{suffix}-S", rss_url=f"https://e.com/{suffix}s.rss")
    show_other = Show(
        title=f"pytest-asr-{suffix}-O", rss_url=f"https://e.com/{suffix}o.rss"
    )
    db_session.add_all([show_s, show_other])
    await db_session.commit()
    await db_session.refresh(show_s)
    await db_session.refresh(show_other)

    rows = [
        AsrCorrectionTerm(wrong=f"G{suffix}", correct="g", scope="global", enabled=True),
        AsrCorrectionTerm(
            wrong=f"H{suffix}", correct="h", scope="show", show_id=show_s.id, enabled=True
        ),
        AsrCorrectionTerm(
            wrong=f"K{suffix}",
            correct="k",
            scope="show",
            show_id=show_other.id,
            enabled=True,
        ),
        AsrCorrectionTerm(
            wrong=f"D{suffix}", correct="d", scope="global", enabled=False
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    yield {
        "show_s": show_s.id,
        "g": f"G{suffix}",
        "h": f"H{suffix}",
        "k": f"K{suffix}",
        "disabled": f"D{suffix}",
        "suffix": suffix,
    }

    await db_session.execute(
        delete(AsrCorrectionTerm).where(AsrCorrectionTerm.wrong.like(f"%{suffix}"))
    )
    await db_session.execute(
        delete(Show).where(Show.id.in_([show_s.id, show_other.id]))
    )
    await db_session.commit()


@pytest.mark.skipif(not _postgres_reachable(), reason="no local Postgres")
async def test_load_rules_unions_global_and_show_excludes_others_and_disabled(
    db_session, rules_fixture
):
    f = rules_fixture
    rules = await load_rules(db_session, f["show_s"])
    wrongs = {r.wrong for r in rules}
    assert f["g"] in wrongs, "enabled global rule must be included"
    assert f["h"] in wrongs, "enabled show-S rule must be included"
    assert f["k"] not in wrongs, "other show's rule must be excluded"
    assert f["disabled"] not in wrongs, "disabled rule must be excluded"


# ─── asr-llm-homophone-postprocess (EQ2b): approval-gated resolution ───


@pytest_asyncio.fixture
async def approval_rules_fixture(db_session):
    """Seed one show with an approved show rule, a pending LLM candidate, and a
    rejected rule — all show-scoped to the same show — to exercise the
    status gate in load_rules. Cleans up by `wrong` suffix."""
    from sqlalchemy import delete

    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    show_s = Show(
        title=f"pytest-asrappr-{suffix}-S", rss_url=f"https://e.com/{suffix}a.rss"
    )
    db_session.add(show_s)
    await db_session.commit()
    await db_session.refresh(show_s)

    rows = [
        AsrCorrectionTerm(
            wrong=f"APPR{suffix}",
            correct="approved",
            scope="show",
            show_id=show_s.id,
            enabled=True,
            source="manual",
            status="approved",
        ),
        # pending LLM candidate — disabled + pending: must be excluded.
        AsrCorrectionTerm(
            wrong=f"PEND{suffix}",
            correct="pending",
            scope="show",
            show_id=show_s.id,
            enabled=False,
            source="llm",
            status="pending",
        ),
        # rejected rule: must be excluded even though it could be re-enabled.
        AsrCorrectionTerm(
            wrong=f"REJ{suffix}",
            correct="rejected",
            scope="show",
            show_id=show_s.id,
            enabled=False,
            source="llm",
            status="rejected",
        ),
        # approved enabled global rule: must be included.
        AsrCorrectionTerm(
            wrong=f"GAPPR{suffix}",
            correct="g",
            scope="global",
            enabled=True,
            source="manual",
            status="approved",
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    yield {
        "show_s": show_s.id,
        "approved": f"APPR{suffix}",
        "pending": f"PEND{suffix}",
        "rejected": f"REJ{suffix}",
        "global_approved": f"GAPPR{suffix}",
        "suffix": suffix,
    }

    await db_session.execute(
        delete(AsrCorrectionTerm).where(AsrCorrectionTerm.wrong.like(f"%{suffix}"))
    )
    await db_session.execute(delete(Show).where(Show.id == show_s.id))
    await db_session.commit()


@pytest.mark.skipif(not _postgres_reachable(), reason="no local Postgres")
async def test_load_rules_excludes_pending_and_rejected_unions_approved(
    db_session, approval_rules_fixture
):
    f = approval_rules_fixture
    rules = await load_rules(db_session, f["show_s"])
    wrongs = {r.wrong for r in rules}
    assert f["approved"] in wrongs, "approved enabled show rule must be included"
    assert f["global_approved"] in wrongs, "approved enabled global rule must be unioned"
    assert f["pending"] not in wrongs, "pending LLM candidate must be excluded"
    assert f["rejected"] not in wrongs, "rejected rule must be excluded"
