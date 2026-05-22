"""Tests for agent-token-budget-and-tool-truncate change.

Covers three spec requirements:
  1. Tool dispatch SHALL truncate result strings sent to the LLM
  2. Agent loop SHALL guard per-round token budget before each LLM call
  3. Agent loop SHALL convert LLM 4xx context-exceeded into envelope (not 5xx)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.services.chat_agent.agent import (
    _CONTEXT_EXCEEDED_USER_HINT,
    _apply_budget_guard,
    _classify_llm_exception,
    _estimate_messages_tokens,
    _truncate_for_llm,
)


# ──────────────────────────────────────────────────────────────────────
# Requirement 1: Tool dispatch truncate
# ──────────────────────────────────────────────────────────────────────


def test_truncate_long_string_appends_suffix():
    s = "x" * 20000
    out = _truncate_for_llm(s, cap=8000)
    assert len(out) >= 8000  # cap + suffix
    assert out.startswith("x" * 8000)
    assert "(truncated," in out
    assert "12000 chars omitted" in out


def test_truncate_short_string_unchanged():
    s = "x" * 300
    out = _truncate_for_llm(s, cap=8000)
    assert out == s
    assert "(truncated" not in out


def test_truncate_at_exact_cap_unchanged():
    s = "x" * 8000
    out = _truncate_for_llm(s, cap=8000)
    assert out == s
    assert "(truncated" not in out


# ──────────────────────────────────────────────────────────────────────
# Requirement 2: Per-round token-budget guard
# ──────────────────────────────────────────────────────────────────────


def test_estimate_messages_tokens_returns_positive_int():
    messages = [
        {"role": "system", "content": "abc" * 100},
        {"role": "user", "content": "hello"},
    ]
    n = _estimate_messages_tokens(messages)
    assert isinstance(n, int)
    assert n > 0


def test_budget_guard_pops_oldest_tool_when_over_budget():
    # Use real-world-ish Chinese transcript so tiktoken BPE doesn't merge
    # repeated chars away (a long run of 'x' compresses to ~50 tokens
    # under BPE; that's a tiktoken artifact, not real workload).
    big = ("迪拉胖在這集深入聊到馬力全開的開工歌單觀念，從中老年人的視角分享。" * 200)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user q"},
        {"role": "tool", "tool_call_id": "t0", "content": big},
        {"role": "tool", "tool_call_id": "t1", "content": big},
        {"role": "tool", "tool_call_id": "t2", "content": "small"},
        {"role": "assistant", "content": "wrap up"},
    ]
    initial = _estimate_messages_tokens(messages)
    # Budget below initial but above just-system+user+last-pair
    budget = initial // 3
    fits, popped = _apply_budget_guard(messages, budget=budget)
    assert fits is True
    assert popped >= 1
    # Oldest tool (t0) should be popped first
    remaining_tool_ids = [m.get("tool_call_id") for m in messages if m.get("role") == "tool"]
    assert "t0" not in remaining_tool_ids


def test_budget_guard_cannot_fit_returns_false():
    # Only 1 tool in messages, and it's in the last-2 protected zone.
    # Set budget to 1 token so any non-empty content trips it. The guard
    # should detect no removable tool and return False without infinite loop.
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
        {"role": "tool", "tool_call_id": "t0", "content": "stuff"},  # protected
        {"role": "assistant", "content": "a"},
    ]
    fits, popped = _apply_budget_guard(messages, budget=1)
    assert fits is False
    # popped 0 since the only tool is in last-2 protected zone
    assert popped == 0


# ──────────────────────────────────────────────────────────────────────
# Requirement 3: LLM exception classification
# ──────────────────────────────────────────────────────────────────────


def _make_bad_request_error(body_msg: str) -> openai.BadRequestError:
    """Build a synthetic BadRequestError mimicking AI Hub gpt-4o response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.headers = {}
    exc = openai.BadRequestError(
        message=body_msg,
        response=mock_resp,
        body={"error": {"message": body_msg, "code": "400"}},
    )
    return exc


def test_classify_context_exceeded_recognized():
    exc = _make_bad_request_error(
        "litellm.ContextWindowExceededError: This model's maximum context length is 128000"
    )
    assert _classify_llm_exception(exc) == "context_exceeded"


def test_classify_other_400_returns_none():
    exc = _make_bad_request_error("Invalid argument: missing required field")
    assert _classify_llm_exception(exc) is None


def test_classify_non_openai_exception_returns_none():
    assert _classify_llm_exception(ValueError("not openai")) is None
    assert _classify_llm_exception(RuntimeError("transient")) is None


def test_context_exceeded_user_hint_is_user_friendly():
    """The hint must NOT contain internal exception class names or 技術問題-style phrasing."""
    h = _CONTEXT_EXCEEDED_USER_HINT
    assert "BadRequestError" not in h
    assert "ContextWindowExceededError" not in h
    assert "技術問題" not in h
    assert "系統錯誤" not in h
    # Must contain helpful user-facing hint
    assert "內容" in h or "拆" in h or "縮小" in h
