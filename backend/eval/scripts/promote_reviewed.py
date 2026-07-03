"""Promote human-approved staging items into a show's main dataset.

Reads the staging file (`_pending_review.json`) plus the review log, and
writes items whose latest verdict is `approve` / `approve_edited` into
`backend/eval/datasets/{slug}.json` with review provenance (reviewer id,
review timestamp, review round — per the rag-eval-dataset spec).

Discipline (same three-parameter gate as build_golden_set.py):
- `--target-main`, `--reviewed-by`, `--reviewed-at` MUST all be supplied,
  else exit 2. There is no other output mode — this script's only job is
  the reviewed write, the gate just makes the intent explicit and grep-able.
- Every staging item for the (show, round) MUST have a verdict in the log;
  unreviewed items abort the promotion (exit 3) — no item skips human review.
- `approve_edited` items are taken from the staging file as-is: the reviewer
  edits the staging item in place BEFORE promoting.

Usage:
    python -m backend.eval.scripts.promote_reviewed \
        --staging backend/eval/datasets/_pending_review.json \
        --show-slug yi-jia-yi --round 1 \
        --target-main --reviewed-by jacky --reviewed-at 2026-07-03T10:00:00Z
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .build_golden_set import DATASETS_DIR, _read_review_log

APPROVED_VERDICTS = ("approve", "approve_edited")


def latest_verdicts(entries: list[dict], show_slug: str, round_no: int) -> dict[str, dict]:
    """item_id → latest log entry for this show+round (later lines override)."""
    verdicts: dict[str, dict] = {}
    for e in entries:
        if e.get("show_slug") == show_slug and e.get("round") == round_no:
            verdicts[e["item_id"]] = e
    return verdicts


def promote_items(
    staging_items: list[dict],
    verdicts: dict[str, dict],
    reviewed_by: str,
    reviewed_at: str,
    round_no: int,
) -> tuple[list[dict], list[str]]:
    """Return (promoted_items, unreviewed_ids). Promoted items carry provenance."""
    promoted: list[dict] = []
    unreviewed: list[str] = []
    for item in staging_items:
        entry = verdicts.get(item["id"])
        if entry is None:
            unreviewed.append(item["id"])
            continue
        if entry["verdict"] not in APPROVED_VERDICTS:
            continue
        out = dict(item)
        out.pop("anchor_context", None)  # staging-only review aid
        out["audit_status"] = "approved"
        out["reviewed_by"] = reviewed_by
        out["reviewed_at"] = reviewed_at
        out["review_round"] = round_no
        promoted.append(out)
    return promoted, unreviewed


def merge_into_main(main_path: Path, staging_doc: dict, promoted: list[dict]) -> dict:
    """Append promoted items to the existing main dataset (or create it)."""
    if main_path.exists():
        doc = json.loads(main_path.read_text(encoding="utf-8"))
        existing_ids = {i["id"] for i in doc.get("items", [])}
        collisions = [i["id"] for i in promoted if i["id"] in existing_ids]
        if collisions:
            raise SystemExit(f"[fatal] id collision with main dataset: {collisions}")
        doc.setdefault("items", []).extend(promoted)
    else:
        doc = {
            "schema_version": "2.0",
            "show_id": staging_doc["show_id"],
            "show_slug": staging_doc["show_slug"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "items": promoted,
        }
    return doc


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote reviewed items to main dataset")
    parser.add_argument(
        "--staging", type=Path, default=DATASETS_DIR / "_pending_review.json"
    )
    parser.add_argument("--show-slug", required=True)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--review-log", type=Path, default=DATASETS_DIR / "_review_log.jsonl")
    parser.add_argument("--target-main", action="store_true")
    parser.add_argument("--reviewed-by", default=None)
    parser.add_argument("--reviewed-at", default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Override main dataset path (default datasets/{slug}.json)",
    )
    args = parser.parse_args(argv)

    if not (args.target_main and args.reviewed_by and args.reviewed_at):
        print(
            "[fatal] promotion requires --target-main with --reviewed-by <id> "
            "and --reviewed-at <ISO8601> — same staging discipline as "
            "build_golden_set.py.",
            file=sys.stderr,
        )
        return 2

    staging_doc = json.loads(args.staging.read_text(encoding="utf-8"))
    if staging_doc.get("show_slug") != args.show_slug:
        print(
            f"[fatal] staging file is for show {staging_doc.get('show_slug')!r}, "
            f"not {args.show_slug!r}",
            file=sys.stderr,
        )
        return 2

    verdicts = latest_verdicts(_read_review_log(args.review_log), args.show_slug, args.round)
    promoted, unreviewed = promote_items(
        staging_doc.get("items", []), verdicts, args.reviewed_by, args.reviewed_at, args.round
    )
    if unreviewed:
        print(
            f"[fatal] {len(unreviewed)} staging items have no verdict for round "
            f"{args.round} — every item must pass human review: {unreviewed[:10]}",
            file=sys.stderr,
        )
        return 3

    main_path = args.out or DATASETS_DIR / f"{args.show_slug}.json"
    doc = merge_into_main(main_path, staging_doc, promoted)
    main_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )

    total = len(staging_doc.get("items", []))
    print(
        f"[ok] promoted {len(promoted)}/{total} items → {main_path} "
        f"(rejected {total - len(promoted)})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
