"""count_consistency grader.

Catches LLM number hallucination on enumeration items: if the agent answer text
asserts "N 集 / N 個 / 共 N", the integer SHALL match enumeration_total.

Returns None when item lacks expected_count (signals inapplicable item type).
Returns passed=True when no count pattern is found in the answer (graceful skip).
Returns passed=False only when a count IS asserted AND it disagrees with enumeration_total.
"""
from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    re.compile(r"共\s*(\d+)"),           # 共 26
    re.compile(r"(\d+)\s*集"),           # 26 集
    re.compile(r"(\d+)\s*個"),           # 26 個
]


def _extract_first_count(text: str) -> int | None:
    for pat in _PATTERNS:
        m = pat.search(text)
        if m:
            return int(m.group(1))
    return None


def grade(item: dict[str, Any], agent_response: dict[str, Any]) -> dict[str, Any] | None:
    expected_count = item.get("expected_count")
    if expected_count is None:
        # also check first turn for multi-turn items
        if item.get("is_multi_turn"):
            for turn in item.get("turns") or []:
                if turn.get("expected_count") is not None:
                    expected_count = turn["expected_count"]
                    break
        if expected_count is None:
            return None

    answer = (agent_response or {}).get("answer") or ""
    enum_total = (agent_response or {}).get("enumeration_total")
    detected = _extract_first_count(answer)

    if detected is None:
        return {
            "score": 1.0,
            "passed": True,
            "details": {
                "detected_count": None,
                "enumeration_total": enum_total,
                "expected_count": expected_count,
                "note": "no count pattern in answer; treated as graceful skip",
            },
        }

    if enum_total is not None and detected != enum_total:
        return {
            "score": 0.0,
            "passed": False,
            "details": {
                "detected_count": detected,
                "enumeration_total": enum_total,
                "expected_count": expected_count,
            },
        }

    return {
        "score": 1.0,
        "passed": True,
        "details": {
            "detected_count": detected,
            "enumeration_total": enum_total,
            "expected_count": expected_count,
        },
    }
