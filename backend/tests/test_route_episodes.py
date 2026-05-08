"""Tests for first-layer episode routing + skip-routing helper."""
from __future__ import annotations

import pytest

from app.services import rag, tokenizer


@pytest.fixture(autouse=True)
def _reset_tokenizer():
    tokenizer.reset_for_tests()
    yield
    tokenizer.reset_for_tests()


def test_skip_routing_for_short_query():
    # Single multi-char token → skip
    assert rag._should_skip_routing("迪拉胖")


def test_skip_routing_for_empty():
    assert rag._should_skip_routing("")
    assert rag._should_skip_routing("   ")


def test_skip_routing_for_whitespace_only():
    assert rag._should_skip_routing(" \n\t ")


def test_no_skip_for_normal_question():
    # 「節目名怎麼來的」應該至少 2 個 multi-char token
    assert not rag._should_skip_routing("節目名怎麼來的")


def test_no_skip_for_long_natural_question():
    assert not rag._should_skip_routing("迪拉胖在 EP134 為什麼不挑一首振奮的開工歌？")
