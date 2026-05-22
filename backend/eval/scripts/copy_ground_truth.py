#!/usr/bin/env python3
"""Copy ground_truth_chunk_ids from this-not-that-cool.json into the
nested-schema extended-multi-turn-40 dataset, for every turn whose
`source` is `existing:<old-item-id>`.

Usage:
    python3 backend/eval/scripts/copy_ground_truth.py [--dry-run]

After this script runs, the multi-turn-40 dataset will carry
ground_truth_chunk_ids on every single-turn item whose `source` points
to an existing this-not-that-cool entry (~18 turns). The remaining
gaps (new single-turn + multi-turn t1) need human audit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SRC = Path("backend/eval/datasets/this-not-that-cool.json")
DST = Path("backend/eval/datasets/extended-multi-turn-40.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = json.loads(SRC.read_text())
    dst = json.loads(DST.read_text())

    src_by_id: dict[str, list[str]] = {}
    for it in src["items"]:
        if it.get("ground_truth_chunk_ids"):
            src_by_id[it["id"]] = it["ground_truth_chunk_ids"]
    print(f"source dataset: {len(src['items'])} items, "
          f"{len(src_by_id)} with ground_truth_chunk_ids")

    matched: list[tuple[str, str, int]] = []
    missing: list[tuple[str, str]] = []
    for it in dst["items"]:
        src_ref = it.get("source", "")
        if not src_ref.startswith("existing:"):
            continue
        old_id = src_ref.split(":", 1)[1]
        gt = src_by_id.get(old_id)
        if gt is None:
            missing.append((it["id"], old_id))
            continue
        # existing items in our nested schema are always single-turn
        turn = it["turns"][0]
        turn["ground_truth_chunk_ids"] = list(gt)
        matched.append((it["id"], old_id, len(gt)))

    print(f"\nMatched {len(matched)} turns:")
    for t_id, old_id, n in matched:
        print(f"  {t_id} → {old_id}  ({n} chunk_ids)")
    if missing:
        print(f"\n!! Missing {len(missing)} (existing: source but no entry in old dataset):")
        for t_id, old_id in missing:
            print(f"  {t_id} → {old_id}")

    if args.dry_run:
        print("\n[dry-run] no file written")
        return
    DST.write_text(json.dumps(dst, ensure_ascii=False, indent=2) + "\n")
    print(f"\nWritten: {DST}")


if __name__ == "__main__":
    main()
