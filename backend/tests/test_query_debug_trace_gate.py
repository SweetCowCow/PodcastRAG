"""Tests for admin debug_trace gate on /query endpoint (agent-trace-telemetry).

Direct unit test on `_agent_result_to_response(include_trace=...)` covering
the three spec scenarios:
  - admin+debug_trace=true → response.trace populated, tool_calls.result_full present
  - non-admin+debug_trace=true → no trace, result_full scrubbed to None
  - admin+no debug_trace → no trace
"""

from __future__ import annotations

import uuid

from app.api.query import _agent_result_to_response
from app.schemas.query import ToolCallTrace
from app.services.chat_agent.agent import (
    ChatAgentResult,
    LLMCallTrace,
    StageTimings,
    TokenUsage,
)
from app.services.chat_agent.state import ChatSessionState


def _make_agent_result() -> ChatAgentResult:
    return ChatAgentResult(
        answer="hello",
        tool_calls=[
            ToolCallTrace(
                name="get_show_overview",
                args={},
                result_summary="short",
                raised=None,
                latency_ms=4.2,
                result_full='{"title": "T", "overview": "very long detail..."}',
            )
        ],
        agent_truncated=False,
        l1_state_after=ChatSessionState(session_id=uuid.uuid4()),
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20),
        llm_calls=[
            LLMCallTrace(
                round_index=0,
                latency_ms=123.4,
                prompt_tokens=10,
                completion_tokens=20,
                finish_reason="stop",
                had_tool_calls=False,
            )
        ],
        stage_timings=StageTimings(
            build_messages_ms=1.0,
            state_load_ms=0.5,
            state_save_ms=0.6,
            history_summary_ms=2.0,
            llm_loop_total_ms=150.0,
        ),
    )


def test_admin_with_debug_trace_returns_full_trace():
    """admin + debug_trace=true → response.trace populated."""
    agent_result = _make_agent_result()
    resp = _agent_result_to_response(agent_result, quota_remaining=99, include_trace=True)

    assert resp.trace is not None
    assert len(resp.trace.llm_calls) == 1
    assert resp.trace.llm_calls[0].latency_ms == 123.4
    assert resp.trace.stage_timings.llm_loop_total_ms == 150.0
    # tool_calls.result_full present.
    assert resp.tool_calls is not None
    assert resp.tool_calls[0].result_full is not None
    assert "very long detail" in resp.tool_calls[0].result_full


def test_non_admin_with_debug_trace_no_trace_field():
    """non-admin + debug_trace=true → response.trace is None, result_full scrubbed.

    The endpoint silently ignores debug_trace=true for non-admin callers (no
    4xx). `_agent_result_to_response(include_trace=False)` is what the API
    layer calls when `debug_trace and user.role == "admin"` evaluates False.
    """
    agent_result = _make_agent_result()
    resp = _agent_result_to_response(agent_result, quota_remaining=99, include_trace=False)

    assert resp.trace is None
    assert resp.tool_calls is not None
    assert resp.tool_calls[0].result_full is None
    # result_summary preserved (backwards-compatible default response).
    assert resp.tool_calls[0].result_summary == "short"


def test_admin_without_debug_trace_no_trace_field():
    """admin + no debug_trace → response shape unchanged (no trace field)."""
    agent_result = _make_agent_result()
    resp = _agent_result_to_response(agent_result, quota_remaining=99, include_trace=False)

    assert resp.trace is None
    assert resp.tool_calls[0].result_full is None
