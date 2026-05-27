"""Dataset audit log for b22 / b23 GT 修正（b23-dataset-and-retrieval-rca-fix Phase 1）.

Local 用，列印當前 b22 / b23 在 dataset 內的三層 GT 結構 + audit_notes，便於對照
2026-05-27 修改前後的 diff。本 script 不修改 dataset；要看 diff 用 git diff
backend/eval/datasets/extended-multi-turn-40.json。
"""
from __future__ import annotations

import json
from pathlib import Path

DATASET = Path("backend/eval/datasets/extended-multi-turn-40.json")


def main() -> int:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in data["items"]}
    for iid in ("b22", "b23"):
        it = by_id.get(iid)
        if it is None:
            print(f"!! {iid} not in dataset")
            continue
        must = it.get("ground_truth_chunk_ids_must") or []
        either = it.get("ground_truth_chunk_ids_either") or []
        accept = it.get("ground_truth_chunk_ids_acceptable") or []
        print("=" * 70)
        print(f"## {iid} — {it.get('design_type')}")
        print("=" * 70)
        print(f"Q: {it.get('question', '')[:120]}")
        print(f"\nmust ({len(must)}):")
        for c in must:
            print(f"  - {c}")
        print(f"\neither ({len(either)}):")
        for c in either:
            print(f"  - {c}")
        print(f"\nacceptable ({len(accept)}):")
        for c in accept:
            print(f"  - {c}")
        print("\naudit_notes:")
        for line in (it.get("audit_notes") or "").splitlines():
            print(f"  {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
