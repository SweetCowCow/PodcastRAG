"""Bug fix: `answer_with_chunks` fallback used to return the raw LLM string
verbatim when JSON parsing failed, leaking the JSON wrapping
(`{"answer": "...", "used_chunk_ids": }`) into the chat bubble shown to
the user.

R3.3 prod verification 2026-05-16 caught the leak in two consecutive
queries against the 「這又沒有很屌」 show — the model returned
malformed JSON (`"used_chunk_ids": }` — trailing colon with no value)
roughly 1 in every 5 responses.

Fix: `_extract_answer_from_malformed_json` regex pulls the `answer`
string out even when surrounding JSON is invalid. These tests guard the
salvage path + cover the cases observed in the prod screenshots.
"""
from __future__ import annotations

from app.services.rag import _extract_answer_from_malformed_json


def test_salvage_returns_none_for_no_answer_field():
    assert _extract_answer_from_malformed_json("") is None
    assert _extract_answer_from_malformed_json("not json at all") is None
    assert _extract_answer_from_malformed_json('{"used_chunk_ids": []}') is None


def test_salvage_extracts_clean_string_from_well_formed_inner_field():
    raw = '{"answer": "hello world", "used_chunk_ids": }'
    assert _extract_answer_from_malformed_json(raw) == "hello world"


def test_salvage_preserves_newlines_via_json_unescape():
    raw = (
        '{"answer": "根據目前的資料，馬世芳曾參與過以下幾集節目：'
        '\\n\\n1. EP143[6]。", "used_chunk_ids": }'
    )
    out = _extract_answer_from_malformed_json(raw)
    assert out is not None
    assert "\n\n" in out
    assert "EP143[6]" in out
    assert "馬世芳" in out


def test_salvage_handles_escaped_quotes_inside_answer():
    raw = '{"answer": "他說 \\"我來了\\" 然後就走了", "used_chunk_ids": }'
    out = _extract_answer_from_malformed_json(raw)
    assert out == '他說 "我來了" 然後就走了'


def test_salvage_handles_the_prod_screenshot_exact_pattern():
    """The exact pattern seen in the 2026-05-16 prod verification screenshot
    — multi-line answer, citation refs preserved, malformed `used_chunk_ids`."""
    raw = (
        '{"answer": "根據目前的資料，馬世芳曾參與過以下幾集節目：\\n\\n'
        '1. 與主持人迪拉一起錄製的「也好吃」，這是一個美食相關的節目[6]。\\n'
        '2. 在描述本次 podcast 中，馬世芳是節目的來賓，與迪拉再次合作[3]。\\n\\n'
        '如果需要更具體的集數或內容，可以再進一步查詢相關資料。", '
        '"used_chunk_ids": }'
    )
    out = _extract_answer_from_malformed_json(raw)
    assert out is not None
    # No JSON braces / field names leak through.
    assert '"answer"' not in out
    assert "used_chunk_ids" not in out
    assert not out.startswith("{")
    # Real content preserved.
    assert "馬世芳" in out
    assert "[6]" in out
    assert "[3]" in out
    # Real newlines, not literal `\n`.
    assert "\\n" not in out
    assert "\n" in out
