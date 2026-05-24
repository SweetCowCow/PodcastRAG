"""Tests for run_chat_agent_eval.py trace capture + env-based credentials.

Covers spec requirements:
  - Chat agent eval runner SHALL capture debug_trace into result JSON
  - Chat agent eval runner SHALL read credentials from environment variables, not argv
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import pytest


# Import the runner module — its path is backend/scripts/run_chat_agent_eval.py
@pytest.fixture()
def runner_module():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    if "run_chat_agent_eval" in sys.modules:
        del sys.modules["run_chat_agent_eval"]
    import run_chat_agent_eval  # type: ignore

    yield run_chat_agent_eval


def _admin_trace_response(answer: str = "EP66 是某集...") -> dict:
    """Shape of a /query?debug_trace=true response when admin gate fires."""
    return {
        "answer": answer,
        "query_id": "q-test",
        "citations": [],
        "quota_remaining": -1,
        "tool_calls": [
            {
                "name": "find_episodes_by_date",
                "args": {"show_id": "x", "start_date": "2024-11-01", "end_date": "2024-11-30"},
                "result_summary": "found 3 episodes",
                "result_full": json.dumps([{"ep_number": 66}, {"ep_number": 67}, {"ep_number": 68}]),
                "latency_ms": 123.4,
                "raised": None,
            }
        ],
        "trace": {
            "llm_calls": [
                {
                    "round_index": 0,
                    "latency_ms": 800.0,
                    "prompt_tokens": 1200,
                    "completion_tokens": 200,
                    "finish_reason": "stop",
                    "had_tool_calls": True,
                }
            ],
            "stage_timings": {
                "build_messages_ms": 5.0,
                "state_load_ms": 2.0,
                "state_save_ms": 1.0,
                "history_summary_ms": 0.0,
                "llm_loop_total_ms": 850.0,
            },
        },
    }


def _degraded_response(answer: str = "answer text") -> dict:
    """Shape when admin gate silently denied (non-admin or older backend)."""
    return {
        "answer": answer,
        "query_id": "q-test",
        "citations": [],
        "quota_remaining": 10,
        # tool_calls is None / empty, trace is None per spec
    }


def test_extract_trace_blob_happy(runner_module):
    """Admin response → blob contains tool_calls (full) + llm_calls + stage_timings."""
    blob = runner_module._extract_trace_blob(_admin_trace_response())
    assert blob is not None
    assert len(blob["tool_calls"]) == 1
    assert blob["tool_calls"][0]["name"] == "find_episodes_by_date"
    assert blob["tool_calls"][0]["args"]["start_date"] == "2024-11-01"
    assert blob["tool_calls"][0]["result_full"]
    assert len(blob["llm_calls"]) == 1
    assert blob["stage_timings"]["llm_loop_total_ms"] == 850.0


def test_extract_trace_blob_degraded_returns_none_and_warns(runner_module):
    """Non-admin response → returns None + prints one-time stderr warning."""
    # reset module-level once-flag to test fresh emission
    runner_module._TRACE_DEGRADE_WARNED = False
    buf = io.StringIO()
    with redirect_stderr(buf):
        blob = runner_module._extract_trace_blob(_degraded_response())
    assert blob is None
    err = buf.getvalue()
    assert "debug_trace silently denied" in err
    assert "degraded" in err


def test_extract_trace_blob_warning_is_once(runner_module):
    """Repeated degraded responses only warn once per process."""
    runner_module._TRACE_DEGRADE_WARNED = False
    buf = io.StringIO()
    with redirect_stderr(buf):
        runner_module._extract_trace_blob(_degraded_response())
        runner_module._extract_trace_blob(_degraded_response())
        runner_module._extract_trace_blob(_degraded_response())
    occurrences = buf.getvalue().count("debug_trace silently denied")
    assert occurrences == 1


def test_main_exits_when_session_env_missing(runner_module, monkeypatch, tmp_path):
    """No PODCASTRAG_SESSION env → exit 2 + stderr error message before any HTTP."""
    monkeypatch.delenv("PODCASTRAG_SESSION", raising=False)
    dataset = tmp_path / "ds.json"
    dataset.write_text(json.dumps({"show_id": "x", "items": []}))
    out = tmp_path / "out.json"
    args = [
        "run_chat_agent_eval.py",
        "--dataset", str(dataset),
        "--backend-url", "http://example.invalid",
        "--label", "test",
        "--out", str(out),
    ]
    monkeypatch.setattr(sys, "argv", args)
    buf = io.StringIO()
    with redirect_stderr(buf), pytest.raises(SystemExit) as exc_info:
        runner_module.main()
    assert exc_info.value.code == 2
    assert "PODCASTRAG_SESSION" in buf.getvalue()


def test_main_reads_session_from_env(runner_module, monkeypatch, tmp_path):
    """PODCASTRAG_SESSION set → main() proceeds past env check (then fails on
    network because the backend URL is invalid — that's OK, we just need to
    verify the env-check gate doesn't trip)."""
    monkeypatch.setenv("PODCASTRAG_SESSION", "sk-fake-admin-session")
    # Stub run_eval so we don't hit the network — verify it received the env token
    captured = {}

    def fake_run_eval(*, dataset_path, backend_url, auth_token, top_k, label):
        captured["auth_token"] = auth_token
        return {"label": label, "dataset": str(dataset_path), "show_id": "x",
                "top_k": top_k, "timestamp": "now", "aggregate": {}}

    monkeypatch.setattr(runner_module, "run_eval", fake_run_eval)

    dataset = tmp_path / "ds.json"
    dataset.write_text(json.dumps({"show_id": "x", "items": []}))
    out = tmp_path / "out.json"
    args = [
        "run_chat_agent_eval.py",
        "--dataset", str(dataset),
        "--backend-url", "http://example.invalid",
        "--label", "test",
        "--out", str(out),
    ]
    monkeypatch.setattr(sys, "argv", args)
    runner_module.main()
    assert captured["auth_token"] == "sk-fake-admin-session"
