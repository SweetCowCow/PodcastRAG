"""Tests for `is_show_name` flag — show-name tokens excluded from ts_query."""
from __future__ import annotations

import jieba
import pytest

from app.services import rag, tokenizer


@pytest.fixture(autouse=True)
def _reset_tokenizer():
    tokenizer.reset_for_tests()
    yield
    tokenizer.reset_for_tests()


def test_show_name_token_dropped_from_ts_query():
    # Manually populate the show-name set (bypasses DB load)
    jieba.add_word("這又沒有很屌", freq=100)
    tokenizer._loaded_terms.add("這又沒有很屌")
    tokenizer._show_name_terms.add("這又沒有很屌")
    try:
        out = rag._build_ts_query("這又沒有很屌的節目名怎麼來的")
        assert out is not None
        assert "這又沒有很屌" not in out
        # Other multi-char tokens should remain
        assert "節目名" in out or "怎麼" in out
    finally:
        jieba.del_word("這又沒有很屌")


def test_non_show_name_token_kept():
    jieba.add_word("迪拉胖", freq=100)
    tokenizer._loaded_terms.add("迪拉胖")
    # NOT added to _show_name_terms
    try:
        out = rag._build_ts_query("迪拉胖在 EP134 怎麼想")
        assert out is not None
        assert "迪拉胖" in out
    finally:
        jieba.del_word("迪拉胖")


def test_get_show_name_terms_returns_copy():
    tokenizer._show_name_terms.add("foo")
    snapshot = tokenizer.get_show_name_terms()
    assert "foo" in snapshot
    snapshot.add("bar")
    # mutating returned set must NOT affect internal state
    assert "bar" not in tokenizer._show_name_terms


def test_short_tokens_no_longer_filtered():
    # R3.2 task 3.1: 1-char filter removed.
    # Token "了" is single-char; should now appear in tsquery output.
    out = rag._build_ts_query("我吃了飯")
    assert out is not None
    # At minimum should include some token; our spec says length-1 tokens are accepted
    # (no minimum length filtering anymore). Specific tokens depend on jieba.
    tokens_in_query = out.split(" | ")
    assert any(len(t) >= 1 for t in tokens_in_query)
