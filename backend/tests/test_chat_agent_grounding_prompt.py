"""Snapshot-style test for SYSTEM_PROMPT grounding section
(agentic-prompt-grounding-and-ordinal-tool change).

Verifies the prompt contains the 6 fabrication-forbidden categories,
the inference disclaimer phrase, and the tool routing hint mentioning
`list_episodes` — those phrases are load-bearing for the LLM judge
severe rate gate (target ≤ 0.10 vs baseline 0.20).
"""
from __future__ import annotations

from app.services.chat_agent.prompts import SYSTEM_PROMPT


def test_six_fabrication_categories_appear_verbatim():
    """All 6 grounding categories must appear in SYSTEM_PROMPT."""
    expected = [
        "節目名稱",
        "來賓",
        "EP 編號",
        "集數標題",
        "來賓具體 quote",
        "統計數字",
    ]
    for phrase in expected:
        assert phrase in SYSTEM_PROMPT, f"missing grounding category: {phrase}"


def test_insufficient_info_disclaimer_present():
    """When tool result insufficient → '資料不足' disclaimer."""
    assert "資料不足，無法確認" in SYSTEM_PROMPT


def test_inference_disclaimer_phrase_present():
    """Inference-content disclaimer phrase."""
    assert "請以節目實際內容為準" in SYSTEM_PROMPT


def test_tool_routing_hint_mentions_list_episodes():
    """Tool routing分工 section mentions list_episodes for sort/limit
    queries."""
    assert "list_episodes" in SYSTEM_PROMPT
    assert "sort 或限定數量" in SYSTEM_PROMPT
    assert "find_episodes_by_date_range" in SYSTEM_PROMPT


def test_grounding_section_heading_present():
    assert "【事實 grounding 規則" in SYSTEM_PROMPT
