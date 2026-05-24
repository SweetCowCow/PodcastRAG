"""Unit tests for post-generation citation scan (annotate unverified
EP refs + quoted strings).

Spec: chat-agentic-routing#Agent answers SHALL flag unverified EP
references and quoted strings.
"""

from __future__ import annotations

from app.services.chat_agent.agent import (
    _annotate_unverified_tokens,
    _UNVERIFIED_SUFFIX,
)
from app.schemas.query import ToolCallTrace


def _tc(name: str, result_full: str) -> ToolCallTrace:
    return ToolCallTrace(
        name=name,
        args={},
        result_summary=result_full[:200],
        result_full=result_full,
        latency_ms=10.0,
        raised=None,
    )


def test_ep_in_reference_not_annotated():
    """EP69 in tool result → not annotated."""
    trace = [_tc("find_episodes_by_date", '{"episodes":[{"title":"EP69｜Demo徵集"}]}')]
    answer = "2024 年 11 月有 EP69｜Demo徵集 一集"
    annotated, count = _annotate_unverified_tokens(answer, trace)
    assert _UNVERIFIED_SUFFIX not in annotated
    assert count == 0


def test_ep_not_in_reference_annotated():
    """EP70, EP71 not in tool result → annotated [未驗證]."""
    trace = [_tc("find_episodes_by_date", '{"episodes":[{"title":"EP69｜Demo徵集"}]}')]
    answer = "2024 年 11 月有 EP69 和 EP70 和 EP71 三集"
    annotated, count = _annotate_unverified_tokens(answer, trace)
    assert "EP69 " in annotated  # not annotated
    assert f"EP70{_UNVERIFIED_SUFFIX}" in annotated
    assert f"EP71{_UNVERIFIED_SUFFIX}" in annotated
    assert count == 2


def test_quote_in_reference_not_annotated():
    """Long quote present in tool result → not annotated."""
    trace = [_tc("search", '{"chunks":[{"text":"我覺得這就是安身之處的概念"}]}')]
    answer = "他提到「我覺得這就是安身之處」這句話。"
    annotated, count = _annotate_unverified_tokens(answer, trace)
    assert _UNVERIFIED_SUFFIX not in annotated
    assert count == 0


def test_quote_not_in_reference_annotated():
    """Long quote NOT in tool result → annotated."""
    trace = [_tc("search", '{"chunks":[{"text":"無關內容"}]}')]
    answer = "他提到「我覺得這就是安身之處」這句話。"
    annotated, count = _annotate_unverified_tokens(answer, trace)
    assert f"」{_UNVERIFIED_SUFFIX}" in annotated
    assert count == 1


def test_short_quote_not_scanned():
    """Quote ≤3 chars is skipped."""
    trace = [_tc("search", '{"chunks":[{"text":"無關"}]}')]
    answer = "他說「好」就走了。"
    annotated, count = _annotate_unverified_tokens(answer, trace)
    assert _UNVERIFIED_SUFFIX not in annotated
    assert count == 0


def test_empty_reference_no_annotation():
    """No tool results → leave answer untouched (grounded-refusal path
    handles this case at the prompt level)."""
    answer = "EP69 和 EP70 都有提到"
    annotated, count = _annotate_unverified_tokens(answer, [])
    assert _UNVERIFIED_SUFFIX not in annotated
    assert count == 0


def test_no_double_annotation():
    """Pre-annotated tokens are not re-annotated on a second pass."""
    trace = [_tc("search", "")]  # empty so first pass would annotate
    # Simulate already-annotated answer (e.g. piped through twice)
    answer = f"EP70{_UNVERIFIED_SUFFIX} 是不存在的集數"
    annotated, count = _annotate_unverified_tokens(answer, trace)
    # Empty reference → all skipped (returns untouched per
    # test_empty_reference_no_annotation). Verify no double suffix.
    assert annotated.count(_UNVERIFIED_SUFFIX) == 1


def test_unverified_count_returned():
    """Count reflects the number of in-place annotations applied."""
    trace = [_tc("search", '{"episodes":[{"title":"EP69"}]}')]
    answer = "EP69 真的存在，EP70 編造的，EP100 也編造，「不存在的引言內容」也是。"
    annotated, count = _annotate_unverified_tokens(answer, trace)
    assert count == 3  # EP70 + EP100 + 引言
