"""Tests for `_build_ts_query` stop-word and 1-char filters.

Covers spec requirements:
- "Lexical query builder SHALL filter stop-words from jieba token stream"
- "Lexical query builder SHALL drop single-character tokens"

See `openspec/changes/retrieve-hybrid-lexical-stopword-filter/`.
"""
from __future__ import annotations

import pytest

from app.services.rag import _STOP_WORDS, _build_ts_query


def _tokens(ts: str | None) -> list[str]:
    """Split the OR-joined tsquery string back into tokens."""
    if ts is None:
        return []
    return [t.strip() for t in ts.split(" | ") if t.strip()]


def test_b20_query_token_count():
    """b20 reference query: 16 raw tokens → ≤10 after filters, no stop-words."""
    q = (
        "迪拉胖在 EP134 為什麼不挑一首振奮的開工歌？"
        "他選的歌想表達什麼概念？"
    )
    ts = _build_ts_query(q)
    toks = _tokens(ts)

    assert ts is not None, "b20 query should yield a non-empty tsquery"
    assert len(toks) <= 10, f"expected ≤10 tokens, got {len(toks)}: {toks}"
    forbidden = {"的", "不", "什麼", "在", "為", "一首"}
    leaked = forbidden & set(toks)
    assert not leaked, f"stop-words leaked into tsquery: {leaked}"


def test_pure_stopword_query_returns_none():
    """All-stop-word question → None → semantic-only fallback."""
    assert _build_ts_query("為什麼？") is None


def test_1char_cjk_dropped():
    """Single-character CJK tokens are filtered out."""
    # 「我去了那裡」 — every jieba token is either stop-word or 1-char CJK.
    ts = _build_ts_query("我去了那裡")
    toks = _tokens(ts)
    for tok in toks:
        assert len(tok) >= 2, f"1-char token leaked: {tok!r}"


def test_multichar_english_preserved():
    """Multi-character English tokens survive both filters."""
    ts = _build_ts_query("RAG EP134 怎麼用？")
    toks = _tokens(ts)
    assert "RAG" in toks, f"RAG missing from {toks}"
    assert "EP134" in toks, f"EP134 missing from {toks}"
    assert "怎麼" not in toks, f"stop-word 怎麼 leaked into {toks}"
    assert "用" not in toks, f"1-char token 用 leaked into {toks}"


def test_stop_words_set_immutable():
    """`_STOP_WORDS` is a `frozenset`; mutation raises AttributeError."""
    with pytest.raises(AttributeError):
        _STOP_WORDS.add("test")  # type: ignore[attr-defined]
