"""Cost + latency tracker (task 1.4).

`MODEL_PRICING` is hardcoded — AI Hub gemini-2.5-flash defaults. Update if
the bake-off settles on a different model. Adapters call `track_call(...)`
around each LLM invocation; tracker accumulates per turn / per session.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Iterator


# USD per 1M tokens. AI Hub pricing as of 2026-05-19 (verify before publishing).
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash-lite": {"input": 0.0375, "output": 0.15},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


def token_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = MODEL_PRICING.get(model)
    if p is None:
        return 0.0
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


@dataclass
class CallRecord:
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float


@dataclass
class TurnTracker:
    """Accumulator for one turn (= one user question)."""
    calls: list[CallRecord] = field(default_factory=list)
    started_at_ns: int = field(default_factory=time.perf_counter_ns)

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> CallRecord:
        cost = token_cost(model, input_tokens, output_tokens)
        rec = CallRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
        )
        self.calls.append(rec)
        return rec

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def llm_latency_sum_ms(self) -> float:
        return sum(c.latency_ms for c in self.calls)

    def wall_latency_ms(self) -> float:
        return (time.perf_counter_ns() - self.started_at_ns) / 1_000_000


@contextmanager
def time_block() -> Iterator[dict]:
    """Sync helper: `with time_block() as t: ...; t['ms']` populated on exit."""
    out: dict = {"ms": 0.0}
    started = time.perf_counter_ns()
    try:
        yield out
    finally:
        out["ms"] = (time.perf_counter_ns() - started) / 1_000_000


@asynccontextmanager
async def atime_block() -> Iterator[dict]:
    out: dict = {"ms": 0.0}
    started = time.perf_counter_ns()
    try:
        yield out
    finally:
        out["ms"] = (time.perf_counter_ns() - started) / 1_000_000


def usage_from_openai_response(resp) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from an OpenAI-compatible response."""
    u = getattr(resp, "usage", None)
    if u is None:
        return (0, 0)
    return (
        int(getattr(u, "prompt_tokens", 0) or 0),
        int(getattr(u, "completion_tokens", 0) or 0),
    )
