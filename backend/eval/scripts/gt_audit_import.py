#!/usr/bin/env python3
"""Stage 3 of L3 ground-truth audit: read the human-marked markdown report
and write the kept chunk_ids back into the extended-multi-turn-40 dataset.

Usage:
    python3 backend/eval/scripts/gt_audit_import.py --in /tmp/gt_audit_l3_batch.md

The script:
  - Parses each `## <item_id> t<n>` section.
  - For every `| [x] | \`<chunk_id>\` | ...` row, appends chunk_id to that
    turn's ground_truth_chunk_ids list.
  - Sets `ground_truth_audit_status: "reviewed"` and audit_date on the turn.
  - If a turn has 0 kept rows AND a `note` mentioning "null", writes
    `ground_truth_chunk_ids: null` instead and records the note.
  - Leaves other turns alone.

Run after gt_audit_export.py + human review in editor.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

DATASET = Path("backend/eval/datasets/extended-multi-turn-40.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    args = ap.parse_args()

    md = Path(args.src).read_text()
    dataset = json.loads(DATASET.read_text())
    items_by_id = {it["id"]: it for it in dataset["items"]}

    # Split sections — each starts with "## <id> t<n>"
    sections = re.split(r"^## ", md, flags=re.M)[1:]
    today = date.today().isoformat()
    summary: list[tuple[str, int, int, str]] = []

    for sec in sections:
        m = re.match(r"(\S+) t(\d+)", sec)
        if not m:
            continue
        item_id, turn_idx_str = m.group(1), int(m.group(2))
        item = items_by_id.get(item_id)
        if not item:
            print(f"  ! skipping unknown item: {item_id}")
            continue
        turn = item["turns"][turn_idx_str - 1]

        kept_chunks = re.findall(r"^\| \[x\] \| `([^`]+)` \|", sec, flags=re.M)
        # Capture note line (everything after **note**：until end of section)
        note_match = re.search(r"\*\*note\*\*：(.*?)(?=\n##|\Z)", sec, flags=re.S)
        note = note_match.group(1).strip() if note_match else ""

        if not kept_chunks and "null" in note.lower():
            turn["ground_truth_chunk_ids"] = None
        else:
            turn["ground_truth_chunk_ids"] = kept_chunks
        turn["ground_truth_audit_status"] = "reviewed"
        turn["ground_truth_audit_date"] = today
        if note:
            turn["ground_truth_review_notes"] = note
        kind = "null" if turn["ground_truth_chunk_ids"] is None else f"{len(kept_chunks)} chunks"
        summary.append((item_id, turn_idx_str, len(kept_chunks), kind))

    DATASET.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n")
    print(f"Updated {len(summary)} turns:")
    for s in summary:
        print(f"  {s[0]} t{s[1]}: {s[3]}")
    print(f"\nWritten: {DATASET}")


if __name__ == "__main__":
    main()
