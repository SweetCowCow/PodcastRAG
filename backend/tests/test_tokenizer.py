"""Tokeniser unit tests.

Covers basic jieba cut behaviour and the custom-dictionary load/reload
cycle. Custom-dict + DB tests are gated on Postgres availability.
"""
from __future__ import annotations

import jieba
import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.tokenizer_term import TokenizerCustomTerm
from app.services import tokenizer
from tests.conftest import _postgres_reachable


@pytest.fixture(autouse=True)
def _reset_tokenizer():
    tokenizer.reset_for_tests()
    yield
    tokenizer.reset_for_tests()


def test_tokenize_strips_whitespace_and_returns_tokens():
    out = tokenizer.tokenize("   你好 世界  ")
    assert out, "expected non-empty token list"
    # the result should be the same with or without the surrounding whitespace
    assert tokenizer.tokenize("你好 世界") == out


def test_empty_string_returns_empty_list():
    assert tokenizer.tokenize("") == []
    assert tokenizer.tokenize("   ") == []


def test_unknown_multichar_name_split_without_dict():
    # 蘴月食堂 is OOV for stock jieba; without our dict it should split.
    # (Anchor: stock jieba's HMM occasionally fuses 3-char names like 迪拉胖
    # so we use a 4-char restaurant name from EP143 that is definitely OOV.)
    tokens = list(jieba.cut("蘴月食堂很好吃"))
    assert "蘴月食堂" not in tokens, (
        "stock jieba changed: 蘴月食堂 is now a known term — adjust the test"
    )


def test_add_word_makes_oov_term_a_single_token():
    jieba.add_word("蘴月食堂", freq=100)
    try:
        tokens = tokenizer.tokenize("蘴月食堂很好吃")
        assert "蘴月食堂" in tokens
    finally:
        jieba.del_word("蘴月食堂")


@pytest.mark.asyncio
@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_load_dictionary_picks_up_db_rows(db_session):
    await db_session.execute(
        delete(TokenizerCustomTerm).where(
            TokenizerCustomTerm.term.in_(["迪拉胖", "顏社"])
        )
    )
    db_session.add_all(
        [
            TokenizerCustomTerm(term="迪拉胖", weight=100, source="seed_script"),
            TokenizerCustomTerm(term="顏社", weight=100, source="seed_script"),
        ]
    )
    await db_session.commit()

    try:
        loaded = await tokenizer.load_dictionary(db_session)
        assert loaded >= 2
        assert "迪拉胖" in tokenizer.tokenize("迪拉胖很煩")
        assert "顏社" in tokenizer.tokenize("我喜歡顏社的歌")
    finally:
        await db_session.execute(
            delete(TokenizerCustomTerm).where(
                TokenizerCustomTerm.term.in_(["迪拉胖", "顏社"])
            )
        )
        await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_reload_dictionary_picks_up_newly_added_terms(db_session):
    await db_session.execute(
        delete(TokenizerCustomTerm).where(TokenizerCustomTerm.term == "顏色")
    )
    await db_session.commit()

    await tokenizer.load_dictionary(db_session)
    assert "顏色" not in tokenizer.tokenize("我喜歡顏色出的歌")  # not yet known

    db_session.add(TokenizerCustomTerm(term="顏色", weight=100, source="manual"))
    await db_session.commit()

    try:
        await tokenizer.reload_dictionary(db_session)
        assert "顏色" in tokenizer.tokenize("我喜歡顏色出的歌")
    finally:
        await db_session.execute(
            delete(TokenizerCustomTerm).where(TokenizerCustomTerm.term == "顏色")
        )
        await db_session.commit()
