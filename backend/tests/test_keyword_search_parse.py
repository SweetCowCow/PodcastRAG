"""Unit tests for keyword_search query parsing + tsquery building.

Pure unit tests — no database. The shared tokenizer is seeded with the
multi-character terms these cases rely on (in production these come from the
`tokenizer_custom_terms` / show-title dictionary loaded from the DB).
"""
import jieba
import pytest

from app.services import keyword_search, tokenizer


@pytest.fixture(autouse=True)
def _seeded_dict():
    # Register the terms the assertions depend on, and short-circuit the lazy
    # DB dictionary load so these stay pure unit tests.
    tokenizer.reset_for_tests()
    seeded = ("馬世芳", "滅火器", "歌單")
    for word in seeded:
        jieba.add_word(word)
    tokenizer._loaded = True
    yield
    for word in seeded:
        jieba.del_word(word)
    tokenizer.reset_for_tests()


def test_punctuation_only_query_yields_no_terms():
    assert keyword_search.parse_query("！！！") == []


def test_dedup_preserves_order():
    assert keyword_search.parse_query("馬世芳 馬世芳 滅火器") == ["馬世芳", "滅火器"]


def test_quote_and_or_operator_not_emitted_as_terms():
    terms = keyword_search.parse_query('歌單" OR 滅火器')
    assert '"' not in terms
    assert "OR" not in terms
    assert "or" not in terms
    assert terms == ["歌單", "滅火器"]


def test_tsquery_build():
    terms = ["a", "b)c"]
    assert keyword_search.build_tsquery_and(terms) == "a & b\\)c"
    assert keyword_search.build_tsquery_or(terms) == "a | b\\)c"
