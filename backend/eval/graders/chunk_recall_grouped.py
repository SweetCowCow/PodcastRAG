"""chunk_recall_grouped grader.

Three-tier ground-truth chunk recall:
- _must: every chunk MUST appear in citations
- _either: any one chunk in the group counts (handles chunk-overlap boundaries)
- _acceptable: bonus, doesn't affect score but reported in details

Score = (must_hits + (1 if any either-group chunk hit else 0)) /
        (|must| + (1 if either is non-empty else 0))

Chunk matching uses canonical "ep:<episode_id>@<start_time:.2f>" with 10s window.
"""
from __future__ import annotations

import re
from typing import Any

_CHUNK_RE = re.compile(r"^ep:([0-9a-f-]+)@(\d+\.\d+)$")

# Window in seconds for chunk-time matching (matches existing eval runner default)
DEFAULT_MATCH_WINDOW_S = 10.0


def _parse_chunk_id(cid: str) -> tuple[str, float] | None:
    m = _CHUNK_RE.match(cid)
    if not m:
        return None
    return m.group(1), float(m.group(2))


def _citations_to_ids(citations: list[dict]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for c in citations or []:
        ep = c.get("episode_id")
        st = c.get("start_time")
        if ep and st is not None:
            try:
                out.append((str(ep), float(st)))
            except (TypeError, ValueError):
                continue
    return out


def _chunk_in_retrieved(
    gt: str, retrieved: list[tuple[str, float]], window: float
) -> bool:
    parsed = _parse_chunk_id(gt)
    if not parsed:
        return False
    ep_gt, st_gt = parsed
    for ep_r, st_r in retrieved:
        if ep_r == ep_gt and abs(st_r - st_gt) <= window:
            return True
    return False


def grade(
    item: dict[str, Any],
    agent_response: dict[str, Any],
    *,
    window_s: float = DEFAULT_MATCH_WINDOW_S,
) -> dict[str, Any] | None:
    # Pick scoring scope (single-turn item or turn-level for multi-turn first turn)
    scope = item
    if item.get("is_multi_turn"):
        turns = item.get("turns") or []
        scope = turns[0] if turns else item

    must = scope.get("ground_truth_chunk_ids_must") or []
    either = scope.get("ground_truth_chunk_ids_either") or []
    acceptable = scope.get("ground_truth_chunk_ids_acceptable") or []

    if not must and not either and not acceptable:
        return None  # inapplicable: no chunk-level GT

    citations = (agent_response or {}).get("citations") or []
    retrieved = _citations_to_ids(citations)

    must_hits = sum(1 for c in must if _chunk_in_retrieved(c, retrieved, window_s))
    either_hit = any(_chunk_in_retrieved(c, retrieved, window_s) for c in either)
    either_hit_chunk = next(
        (c for c in either if _chunk_in_retrieved(c, retrieved, window_s)), None
    )
    acceptable_hits = sum(
        1 for c in acceptable if _chunk_in_retrieved(c, retrieved, window_s)
    )

    denominator = len(must) + (1 if either else 0)
    numerator = must_hits + (1 if either_hit else 0)
    score = (numerator / denominator) if denominator > 0 else 0.0
    score = min(score, 1.0)

    return {
        "score": score,
        "passed": score >= 1.0,
        "details": {
            "must_total": len(must),
            "must_hits": must_hits,
            "either_total": len(either),
            "either_group_hit": either_hit,
            "either_hit_chunk": either_hit_chunk,
            "acceptable_total": len(acceptable),
            "acceptable_hits": acceptable_hits,
        },
    }
