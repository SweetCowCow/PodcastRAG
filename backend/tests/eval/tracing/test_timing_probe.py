"""Unit tests for langfuse-sdk-overhead-rca timing probe.

Verifies that `_timed_call` is a zero-cost no-op when `_TIMING_PROBE_ENABLED`
is False, and emits `langfuse_timing:` logger lines when True. Per design
Implementation Contract item 3.
"""
from __future__ import annotations

import logging
import time

import pytest

from eval.tracing import langfuse_setup


def test_probe_disabled_no_log_emission(caplog, monkeypatch):
    """When probe flag is False, _timed_call SHALL NOT emit any logger line."""
    monkeypatch.setattr(langfuse_setup, "_TIMING_PROBE_ENABLED", False)
    caplog.set_level(logging.INFO, logger="eval.tracing.langfuse_setup")

    result, elapsed_ms = langfuse_setup._timed_call(
        "test_span", "test_op", lambda x: x * 2, 21,
    )

    assert result == 42
    assert elapsed_ms == 0.0
    timing_lines = [r for r in caplog.records if "langfuse_timing" in r.message]
    assert len(timing_lines) == 0


def test_probe_enabled_emits_per_op_log(caplog, monkeypatch):
    """When probe flag is True, _timed_call SHALL emit a `langfuse_timing:` line."""
    monkeypatch.setattr(langfuse_setup, "_TIMING_PROBE_ENABLED", True)
    caplog.set_level(logging.INFO, logger="eval.tracing.langfuse_setup")

    def slow_op():
        time.sleep(0.001)
        return "ok"

    result, elapsed_ms = langfuse_setup._timed_call(
        "test_span", "slow_op", slow_op,
    )

    assert result == "ok"
    assert elapsed_ms >= 1.0  # at least 1ms because we slept
    matching = [
        r for r in caplog.records
        if r.message.startswith("langfuse_timing:")
        and "op=slow_op" in r.message
    ]
    assert len(matching) == 1


def test_probe_disabled_zero_overhead(monkeypatch):
    """1000 disabled-probe calls SHALL complete in under 10ms total."""
    monkeypatch.setattr(langfuse_setup, "_TIMING_PROBE_ENABLED", False)

    noop = lambda: None
    t0 = time.perf_counter()
    for _ in range(1000):
        langfuse_setup._timed_call("s", "op", noop)
    total_ms = (time.perf_counter() - t0) * 1000.0

    assert total_ms < 10.0, f"per-call avg {total_ms/1000:.4f}ms exceeds 0.01ms target"
