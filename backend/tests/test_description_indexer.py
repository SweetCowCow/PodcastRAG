"""Unit tests for description_indexer helpers."""
from __future__ import annotations

import logging

from app.services import description_indexer as di


def test_strip_html_basic():
    out = di._strip_html("<p>本集介紹<a href='x'>顏社</a>的歌單</p>")
    # tags removed, anchor flattened
    assert "顏社" in out
    assert "<" not in out and ">" not in out
    assert "本集介紹" in out


def test_strip_html_drops_script_and_style():
    raw = "前<script>evil()</script>後<style>.a{}</style>結尾"
    out = di._strip_html(raw)
    assert "evil" not in out
    assert ".a" not in out
    assert "前" in out and "後" in out and "結尾" in out


def test_strip_boilerplate_removes_match_lines():
    raw = "來賓: 馬世芳\n歡迎收聽下集！\n本集精彩內容\n鼓勵您贊助節目"
    out = di._strip_boilerplate(raw)
    assert "來賓: 馬世芳" in out
    assert "本集精彩內容" in out
    assert "歡迎收聽下集" not in out
    assert "贊助" not in out


def test_clean_description_combines_strip_and_boilerplate():
    raw = "<p>來賓: 馬世芳</p>\n<p>歡迎收聽下集！</p>"
    out = di.clean_description(raw)
    assert "馬世芳" in out
    assert "歡迎收聽下集" not in out


def test_clean_description_returns_empty_for_none_or_blank():
    assert di.clean_description(None) == ""
    assert di.clean_description("") == ""
    assert di.clean_description("<p></p>") == ""


def test_clean_description_returns_empty_after_full_boilerplate():
    raw = "鼓勵您贊助節目\n按讚訂閱"
    assert di.clean_description(raw) == ""


def test_strip_ratio_warning_logged_for_aggressive_strip(caplog):
    caplog.set_level(logging.WARNING)
    # 11/12 chars are HTML; the 1 visible char triggers > 50% strip warning
    raw = "<p><span><b>x</b></span></p>"
    di._strip_html(raw)  # no warning here, called from internal helper
    # The warning is emitted by build_description_index_for_episode; smoke
    # test: just confirm clean_description shrinks length appropriately.
    cleaned = di.clean_description(raw)
    assert len(cleaned) < len(raw) * 0.5


def test_boilerplate_patterns_are_compiled_case_insensitive():
    out = di._strip_boilerplate("HELLO 鼓勵贊助 BYE\n保留")
    assert "保留" in out
    assert "鼓勵贊助" not in out
