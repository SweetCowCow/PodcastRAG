"""ordinal_resolution grader for multi-turn ordinal items (e.g. mt01 t2).

Parses carry_from directives of the form:
    "t<N>.enumeration_episodes[<index>] sorted by published_at <DESC|ASC>"

Reads prior_turn_context to obtain that turn's enumeration_episodes, sorts per the
directive, picks the index — that is the expected_episode_id. Then scans the
current turn's tool_calls for any args.episode_id and compares.
"""
from __future__ import annotations

import re
from typing import Any

_CARRY_RE = re.compile(
    r"t(\d+)\.enumeration_episodes\[(\d+)\]\s+sorted\s+by\s+published_at\s+(DESC|ASC)",
    re.IGNORECASE,
)


def _resolve_expected(
    carry_from: str, prior_turn_context: dict[str, Any]
) -> str | None:
    m = _CARRY_RE.search(carry_from)
    if not m:
        return None
    _t_num, idx_str, order = m.groups()
    idx = int(idx_str)
    reverse = order.upper() == "DESC"

    enum = prior_turn_context.get("enumeration_episodes") or []
    if not enum:
        return None

    sorted_enum = sorted(enum, key=lambda e: e.get("published_at", ""), reverse=reverse)
    if idx >= len(sorted_enum):
        return None
    return sorted_enum[idx].get("episode_id")


def _agent_episode_id_from_tools(tool_calls: list[dict]) -> str | None:
    for tc in tool_calls or []:
        args = tc.get("args") or {}
        if "episode_id" in args:
            return args["episode_id"]
    return None


def grade(
    item: dict[str, Any],
    agent_response: dict[str, Any],
    *,
    prior_turn_context: dict[str, Any] | None = None,
    current_turn_index: int | None = None,
) -> dict[str, Any] | None:
    if not item.get("is_multi_turn"):
        return None

    turns = item.get("turns") or []
    # Default to the LAST turn if not specified
    turn_idx = current_turn_index if current_turn_index is not None else len(turns) - 1
    if turn_idx < 0 or turn_idx >= len(turns):
        return None
    turn = turns[turn_idx]

    if not turn.get("ordinal_resolution_check"):
        return None
    carry_from = turn.get("carry_from")
    if not carry_from:
        return None
    if not prior_turn_context:
        return {
            "score": 0.0,
            "passed": False,
            "details": {"error": "prior_turn_context not supplied to grader"},
        }

    expected_id = _resolve_expected(carry_from, prior_turn_context)
    if not expected_id:
        return {
            "score": 0.0,
            "passed": False,
            "details": {
                "error": "could not resolve expected episode from carry_from",
                "carry_from": carry_from,
            },
        }

    actual_id = _agent_episode_id_from_tools((agent_response or {}).get("tool_calls"))
    passed = actual_id == expected_id
    return {
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "details": {
            "expected_episode_id": expected_id,
            "actual_episode_id": actual_id,
            "carry_from": carry_from,
        },
    }
