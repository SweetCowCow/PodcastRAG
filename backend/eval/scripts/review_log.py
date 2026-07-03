"""Append one human-review verdict to the review log (eval-loop-automation, D4).

The log is append-only JSONL at `backend/eval/datasets/_review_log.jsonl`.
Line schema: {ts, show_slug, item_id, verdict, reason, note, question, round}.
`question` is optional but REQUIRED for rejects — it feeds the reject-feedback
loop as a concrete negative few-shot example.

Usage:
    python -m backend.eval.scripts.review_log \
        --show-slug yi-jia-yi --item-id yijiay-r1-fact-01 \
        --verdict reject --reason too_shallow \
        --note "單句可矇中" --question "主持人養的貓叫什麼名字？" --round 1
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .build_golden_set import DATASETS_DIR, append_review_log

VERDICTS = ("approve", "approve_edited", "reject")

# Human reject reasons (D4). `show_id_guard` is reserved for the machine
# (build_golden_set pre-review) and not accepted here.
REJECT_REASONS = (
    "anchor_mismatch",
    "too_shallow",
    "keyword_triggered",
    "cross_ep_irrelevant",
    "ambiguous",
    "asr_typo_dependent",
    "other",
)


def build_entry(
    show_slug: str,
    item_id: str,
    verdict: str,
    reason: str,
    note: str,
    question: str,
    round_no: int,
) -> dict:
    """Validate and assemble one review-log entry. Raises ValueError on misuse."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    if verdict == "reject":
        if reason not in REJECT_REASONS:
            raise ValueError(f"reject reason must be one of {REJECT_REASONS}, got {reason!r}")
        if reason == "other" and not note:
            raise ValueError("reason 'other' requires a non-empty note")
        if not question:
            raise ValueError("rejects require --question (feeds the negative few-shot loop)")
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "show_slug": show_slug,
        "item_id": item_id,
        "verdict": verdict,
        "reason": reason,
        "note": note,
        "question": question,
        "round": round_no,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a review verdict (JSONL)")
    parser.add_argument("--show-slug", required=True)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--verdict", required=True, choices=VERDICTS)
    parser.add_argument("--reason", default="", help="Required for rejects (enum)")
    parser.add_argument("--note", default="")
    parser.add_argument("--question", default="", help="Item question text (required for rejects)")
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--review-log", type=Path, default=DATASETS_DIR / "_review_log.jsonl")
    args = parser.parse_args(argv)

    try:
        entry = build_entry(
            args.show_slug, args.item_id, args.verdict,
            args.reason, args.note, args.question, args.round,
        )
    except ValueError as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        return 2

    append_review_log(args.review_log, entry)
    print(f"[ok] {args.item_id}: {args.verdict}" + (f" ({args.reason})" if args.reason else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
