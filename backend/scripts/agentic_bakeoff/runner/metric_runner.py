"""Metric runner (task 1.3): one framework adapter × one golden set.

Computes the 5 quantitative metrics defined in design.md:
1. tool_precision      — required tools hit / total required (per turn)
2. answer_keyword_hit  — fraction of expected keywords found in answer
3. wall_latency_ms     — per turn (mean / p50 / p95)
4. cost_usd            — per turn (sum)
5. multi_turn_pass     — fraction of multi-turn dialogs whose FINAL turn passes

Adapters implement the FrameworkAdapter protocol; runner is framework-agnostic.
"""
from __future__ import annotations

import json
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from ..tools.context import ToolContext
from .cost_latency_tracker import TurnTracker


# ---- Adapter protocol ----

class ToolCallTrace(BaseModel):
    name: str
    args: dict[str, Any] = {}
    result_summary: str = ""  # short string for trace logging
    raised: str | None = None  # exception class name if any


class TurnResult(BaseModel):
    answer: str
    tool_calls: list[ToolCallTrace]
    wall_latency_ms: float
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    trace_log: str = ""  # framework-specific debug dump


class FrameworkAdapter(Protocol):
    name: str  # e.g. "a_native_openai" / "b_pydantic_ai" / "e_google_adk"

    async def run_turn(
        self, question: str, session_id: str, ctx: ToolContext
    ) -> TurnResult: ...

    async def reset_session(self, session_id: str) -> None: ...


# ---- Golden set schema ----

class GoldenTurn(BaseModel):
    question: str
    expected_tool_calls_required: list[str] = []
    expected_tool_calls_acceptable: list[str] = []
    expected_answer: str | None = None
    expected_answer_keywords: list[str] = []


class GoldenItem(BaseModel):
    id: str
    design_type: str  # show_overview / guest_find / topic_find / date_find /
                     # deep_dive / cross_episode / summary / negative / multi_turn
    source: str       # existing:q01 / new / multi_turn
    turns: list[GoldenTurn]
    is_multi_turn: bool = False


# ---- Per-turn scoring ----

def score_tool_precision(
    actual: list[str], required: list[str], acceptable: list[str]
) -> float:
    """Required must all be present. Extras count if in acceptable; else penalise.

    Returns 1.0 if all required hit AND no off-list extras.
    0.5 if all required hit but unrelated extras present.
    Otherwise required_hit_rate * 0.5 (partial credit).
    """
    actual_set = set(actual)
    required_set = set(required)
    acceptable_set = set(acceptable)
    if not required_set:
        return 1.0
    required_hit = len(required_set & actual_set) / len(required_set)
    off_list = actual_set - required_set - acceptable_set
    if required_hit == 1.0 and not off_list:
        return 1.0
    if required_hit == 1.0 and off_list:
        return 0.5
    return required_hit * 0.5


def score_keyword_hit(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0  # no keywords specified = vacuous pass
    if not answer:
        return 0.0
    hits = sum(1 for kw in keywords if kw in answer)
    return hits / len(keywords)


# ---- Result types ----

@dataclass
class TurnScore:
    item_id: str
    turn_index: int
    question: str
    tool_precision: float
    answer_keyword_hit: float
    wall_latency_ms: float
    cost_usd: float
    is_final_turn: bool
    is_multi_turn: bool
    actual_tools: list[str] = field(default_factory=list)
    expected_required: list[str] = field(default_factory=list)
    answer_excerpt: str = ""
    raised: list[str] = field(default_factory=list)


@dataclass
class FrameworkRunResult:
    framework: str
    ran_at: str
    turn_scores: list[TurnScore] = field(default_factory=list)

    def aggregate(self) -> dict[str, Any]:
        if not self.turn_scores:
            return {}
        lats = [t.wall_latency_ms for t in self.turn_scores]
        mt_finals = [t for t in self.turn_scores if t.is_multi_turn and t.is_final_turn]
        mt_pass = (
            sum(
                1
                for t in mt_finals
                if t.tool_precision >= 0.99 and t.answer_keyword_hit >= 0.5
            )
            / len(mt_finals)
            if mt_finals
            else None
        )
        return {
            "turns_total": len(self.turn_scores),
            "tool_precision_mean": statistics.mean(t.tool_precision for t in self.turn_scores),
            "answer_keyword_hit_mean": statistics.mean(t.answer_keyword_hit for t in self.turn_scores),
            "latency_p50_ms": statistics.median(lats),
            "latency_p95_ms": sorted(lats)[int(len(lats) * 0.95) - 1] if len(lats) >= 5 else max(lats),
            "latency_mean_ms": statistics.mean(lats),
            "cost_total_usd": sum(t.cost_usd for t in self.turn_scores),
            "multi_turn_final_pass_rate": mt_pass,
            "multi_turn_finals_n": len(mt_finals),
        }


# ---- Main runner ----

async def run_golden_set(
    adapter: FrameworkAdapter,
    golden_path: Path,
    show_id: uuid.UUID,
    redis_url: str | None = None,
) -> FrameworkRunResult:
    """Run one framework adapter through full golden set.

    Each item gets a fresh session_id. Multi-turn items reuse session_id
    across turns so L1 Redis state carries.
    """
    from ..tools.context import ToolContext  # local re-import for clarity

    raw = json.loads(golden_path.read_text())
    items = [GoldenItem.model_validate(it) for it in raw["items"]]

    result = FrameworkRunResult(
        framework=adapter.name,
        ran_at=datetime.now(timezone.utc).isoformat(),
    )

    for item in items:
        session_id = f"bakeoff-{adapter.name}-{item.id}-{uuid.uuid4().hex[:6]}"
        # Fresh context per item so DB session doesn't leak across items.
        # ToolContext.from_env() is callable per-turn for now; an adapter that
        # batches DB sessions can be added later if cost dictates.
        for i, turn in enumerate(item.turns):
            ctx = ToolContext.from_env(show_id=show_id, session_id=session_id)
            is_final = i == len(item.turns) - 1
            tr = await adapter.run_turn(turn.question, session_id, ctx)
            actual_tools = [tc.name for tc in tr.tool_calls]
            tool_p = score_tool_precision(
                actual_tools,
                turn.expected_tool_calls_required,
                turn.expected_tool_calls_acceptable,
            )
            kw_hit = score_keyword_hit(tr.answer, turn.expected_answer_keywords)
            result.turn_scores.append(TurnScore(
                item_id=item.id,
                turn_index=i,
                question=turn.question,
                tool_precision=tool_p,
                answer_keyword_hit=kw_hit,
                wall_latency_ms=tr.wall_latency_ms,
                cost_usd=tr.cost_usd,
                is_final_turn=is_final,
                is_multi_turn=item.is_multi_turn,
                actual_tools=actual_tools,
                expected_required=turn.expected_tool_calls_required,
                answer_excerpt=tr.answer[:200],
                raised=[tc.raised for tc in tr.tool_calls if tc.raised],
            ))
        await adapter.reset_session(session_id)

    return result


def dump_result(result: FrameworkRunResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{result.framework}_{ts}.json"
    payload = {
        "framework": result.framework,
        "ran_at": result.ran_at,
        "aggregate": result.aggregate(),
        "turns": [
            {
                "item_id": t.item_id,
                "turn_index": t.turn_index,
                "question": t.question,
                "tool_precision": t.tool_precision,
                "answer_keyword_hit": t.answer_keyword_hit,
                "wall_latency_ms": t.wall_latency_ms,
                "cost_usd": t.cost_usd,
                "is_final_turn": t.is_final_turn,
                "is_multi_turn": t.is_multi_turn,
                "actual_tools": t.actual_tools,
                "expected_required": t.expected_required,
                "answer_excerpt": t.answer_excerpt,
                "raised": t.raised,
            }
            for t in result.turn_scores
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return out_path
