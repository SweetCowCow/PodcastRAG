"""eval-runner-chat-enum-scoring: tests for the chat-enumeration helper +
union-scoring + non-enum skip semantics.

The runner now augments enumeration scoring with a second backend call
to `POST /shows/{id}/query` so the union of search-side chunks and
chat-side `enumeration_episodes` reflects the user-visible enumeration
list. These tests cover:

- helper success path (returns episode_ids + total)
- helper fail-open paths (5xx, missing CSRF, missing enumeration_episodes
  field, network timeout)
- non-enumeration items skip the chat call entirely (cost contract)
- union scoring math example from the spec scenario
"""
from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

from eval.runners import run as runner


# Reset module-level state between tests so token caches don't leak.
@pytest.fixture(autouse=True)
def _reset_module_state():
    runner._CSRF_CACHE.clear()
    runner._CHAT_CSRF_WARNED.clear()
    yield
    runner._CSRF_CACHE.clear()
    runner._CHAT_CSRF_WARNED.clear()


def _make_http_response(body: dict, status: int = 200):
    """Construct an object urlopen() returns. Only `.read()` is invoked
    by the runner so a tiny BytesIO mock is sufficient."""
    class _Resp:
        def read(self):
            return json.dumps(body).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    return _Resp()


# ---------------------------------------------------------------------------
# helper success
# ---------------------------------------------------------------------------

def test_chat_enumeration_helper_success_returns_ids_and_total():
    """200 OK with valid body — extract episode_ids list + enumeration_total."""
    ep_ids = ["ep-A", "ep-B", "ep-C"]
    body = {
        "enumeration_episodes": [{"episode_id": e} for e in ep_ids],
        "enumeration_total": 3,
    }
    # Seed CSRF cache so _retrieve_chat_enumeration skips the /me fetch
    runner._CSRF_CACHE["TOKEN"] = "csrf-value"
    with patch.object(runner.urllib.request, "urlopen") as mock_open:
        mock_open.return_value = _make_http_response(body)
        out_ids, out_total = runner._retrieve_chat_enumeration(
            "http://backend", "show-id", "馬世芳哪幾集", "TOKEN",
        )
    assert out_ids == ep_ids
    assert out_total == 3


def test_chat_enumeration_helper_falls_back_to_len_when_total_missing():
    """enumeration_total absent → use len(enumeration_episodes)."""
    body = {"enumeration_episodes": [{"episode_id": "ep-A"}, {"episode_id": "ep-B"}]}
    runner._CSRF_CACHE["TOKEN"] = "csrf-value"
    with patch.object(runner.urllib.request, "urlopen") as mock_open:
        mock_open.return_value = _make_http_response(body)
        out_ids, out_total = runner._retrieve_chat_enumeration(
            "http://backend", "show-id", "q", "TOKEN",
        )
    assert out_ids == ["ep-A", "ep-B"]
    assert out_total == 2


# ---------------------------------------------------------------------------
# helper fail-open paths
# ---------------------------------------------------------------------------

def test_chat_enumeration_helper_5xx_returns_empty_and_none(capsys):
    """HTTP 503 → ([], None) + stderr warning containing the question."""
    runner._CSRF_CACHE["TOKEN"] = "csrf-value"
    exc = urllib.error.HTTPError(
        url="http://backend/shows/show-id/query", code=503, msg="Service Unavailable",
        hdrs=None, fp=None,
    )
    with patch.object(runner.urllib.request, "urlopen", side_effect=exc):
        out_ids, out_total = runner._retrieve_chat_enumeration(
            "http://backend", "show-id", "q1", "TOKEN",
        )
    assert out_ids == []
    assert out_total is None
    err = capsys.readouterr().err
    assert "503" in err
    assert "q1" in err


def test_chat_enumeration_helper_no_csrf_returns_empty_with_warning_once(capsys):
    """When /me yields no csrf_token, fail open + warn ONCE per token."""
    # Empty _CSRF_CACHE forces a /me fetch; mock _fetch_csrf returns "".
    with patch.object(runner, "_fetch_csrf", return_value=""):
        out1 = runner._retrieve_chat_enumeration("http://backend", "show-id", "q1", "TOK")
        out2 = runner._retrieve_chat_enumeration("http://backend", "show-id", "q2", "TOK")
    assert out1 == ([], None)
    assert out2 == ([], None)
    err = capsys.readouterr().err
    # Warning appears exactly once across both calls
    assert err.count("chat-enum scoring disabled") == 1


def test_chat_enumeration_helper_missing_field_returns_empty_with_total_zero():
    """200 OK + valid JSON but missing `enumeration_episodes` field →
    ([], 0). Distinct from failure: total=0 not None signals the chat
    path saw the question but didn't classify it as enumeration."""
    body = {"answer": "some prose", "citations": []}  # no enumeration_episodes
    runner._CSRF_CACHE["TOKEN"] = "csrf-value"
    with patch.object(runner.urllib.request, "urlopen") as mock_open:
        mock_open.return_value = _make_http_response(body)
        out_ids, out_total = runner._retrieve_chat_enumeration(
            "http://backend", "show-id", "q", "TOKEN",
        )
    assert out_ids == []
    assert out_total == 0  # NOT None — call succeeded, just no enum


def test_chat_enumeration_helper_timeout_returns_empty_and_none(capsys):
    """Network timeout doesn't propagate; fail-open with stderr warning."""
    runner._CSRF_CACHE["TOKEN"] = "csrf-value"
    with patch.object(runner.urllib.request, "urlopen", side_effect=TimeoutError("read timed out")):
        out = runner._retrieve_chat_enumeration("http://backend", "show-id", "qtimeout", "TOKEN")
    assert out == ([], None)
    err = capsys.readouterr().err
    assert "qtimeout" in err


def test_chat_enumeration_helper_no_token_short_circuits():
    """Empty token = unauthenticated session = chat would 401 anyway.
    Short-circuit without hitting network."""
    # _fetch_csrf shouldn't even be called; assert via spy.
    with patch.object(runner, "_fetch_csrf") as mock_csrf:
        out = runner._retrieve_chat_enumeration("http://backend", "show-id", "q", "")
    assert out == ([], None)
    mock_csrf.assert_not_called()


# ---------------------------------------------------------------------------
# Union scoring math (spec scenario example)
# ---------------------------------------------------------------------------

def test_enumeration_union_scoring_combines_search_and_chat():
    """Spec scenario «Enumeration recall counts both search and chat hits»:
    search yields {ep-A, ep-X}, chat yields {ep-A, ep-B, ep-C, ep-D},
    expected = {ep-A, ep-B, ep-C, ep-D, ep-E}. Union recall = 4/5 = 0.8;
    chat-only recall ALSO = 4/5 = 0.8 (search adds ep-X which isn't in expected)."""
    from eval.metrics.recall import episode_set_recall
    search_eps = ["ep-A", "ep-X"]
    chat_eps = ["ep-A", "ep-B", "ep-C", "ep-D"]
    expected = ["ep-A", "ep-B", "ep-C", "ep-D", "ep-E"]
    union = list(set(search_eps) | set(chat_eps))
    assert episode_set_recall(union, expected) == 0.8
    assert episode_set_recall(chat_eps, expected) == 0.8


# ---------------------------------------------------------------------------
# Non-enumeration items skip chat call (cost contract)
# ---------------------------------------------------------------------------

def test_non_enumeration_items_skip_chat_call(tmp_path):
    """chunk_id / open_set_lenient items SHALL NOT trigger _retrieve_chat_enumeration.

    This is a cost / behavior contract: runs that contain zero enumeration
    items SHALL be identical (same cost, same network footprint) to runs
    prior to this change shipping.
    """
    # Build a minimal dataset of chunk_id + open_set_lenient items.
    dataset = {
        "show_id": "00000000-0000-0000-0000-000000000000",
        "show_slug": "test-show",
        "version": "v0",
        "items": [
            {
                "id": "q01", "type": "fact", "eval_mode": "chunk_id",
                "question": "q1", "ground_truth_chunk_ids": ["ep:x@0.00"],
            },
            {
                "id": "q02", "type": "cross-episode", "eval_mode": "open_set_lenient",
                "question": "q2", "ground_truth_chunk_ids": ["ep:y@1.00"],
            },
        ],
    }
    ds_path = tmp_path / "ds.json"
    ds_path.write_text(json.dumps(dataset))

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    from pathlib import Path
    with patch.object(runner, "_retrieve", return_value=(["ep:x@0.00"], ["t"], 100.0)), \
         patch.object(runner, "_retrieve_chat_enumeration") as mock_chat:
        runner.run_eval(
            dataset_path=Path(str(ds_path)),
            backend_url="http://backend",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=Path(str(out_dir)),
            match_window_s=10.0,
            metric_level="episode",
        )
    # Chat-enumeration helper MUST NOT have been called for these items.
    assert mock_chat.call_count == 0
