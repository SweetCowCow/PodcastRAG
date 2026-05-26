"""v1 → v2 chat-rag dataset migration.

Conservative mechanical conversion:
- DROP expected_answer_keywords (no auto-generate of expected_answer_summary;
  set to literal "PENDING AUDIT" so grader treats item as unverified)
- expected_episode_uuids (single-tier) → expected_episode_uuids_must
- ground_truth_chunk_ids (single-tier) → ground_truth_chunk_ids_must
- Carry expected_tool_calls_required / _acceptable unchanged
- audit_status defaults to "pending"; 7 audited ids (b22/b27/b29/b11/b15/b14/mt01)
  are NOT special-cased here — they get overlaid manually from case study after migration.

Fails loudly (non-zero exit) on any item missing required fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

V1_REQUIRED_TOP_LEVEL = {"items", "show_id"}
V1_REQUIRED_PER_TURN = {"question"}


def _migrate_turn(turn_v1: dict[str, Any]) -> dict[str, Any]:
    missing = V1_REQUIRED_PER_TURN - turn_v1.keys()
    if missing:
        raise KeyError(f"turn missing required v1 fields: {missing}")

    out: dict[str, Any] = {
        "question": turn_v1["question"],
        "expected_behavior": "answer",  # default; audit overlay refines per item
        "expected_answer_summary": "PENDING AUDIT",
        "expected_answer_aliases": None,
        "expected_tool_calls_required": turn_v1.get("expected_tool_calls_required", []),
        "expected_tool_calls_acceptable": turn_v1.get("expected_tool_calls_acceptable", []),
        "expected_tool_args": None,
        "expected_episode_uuids_must": turn_v1.get("expected_episode_uuids") or None,
        "expected_episode_uuids_acceptable": None,
        "expected_episode_numbers_must": None,
        "expected_episode_numbers_acceptable": None,
        "expected_count": None,
        "expected_top_n_episode_numbers": None,
        "expected_must_contradict_check": None,
    }

    gt = turn_v1.get("ground_truth_chunk_ids")
    out["ground_truth_chunk_ids_must"] = list(gt) if gt else None
    out["ground_truth_chunk_ids_either"] = None
    out["ground_truth_chunk_ids_acceptable"] = None

    # Carry over multi-turn hints if present
    if "carry_note" in turn_v1:
        out["carry_from"] = turn_v1["carry_note"]
        out["ordinal_resolution_check"] = True
    if "turn" in turn_v1:
        out["turn"] = turn_v1["turn"]

    return out


def _migrate_item(item_v1: dict[str, Any]) -> dict[str, Any]:
    if "id" not in item_v1:
        raise KeyError(f"item missing 'id': keys={list(item_v1.keys())}")
    if "design_type" not in item_v1:
        raise KeyError(f"item {item_v1['id']} missing 'design_type'")

    out: dict[str, Any] = {
        "id": item_v1["id"],
        "design_type": item_v1["design_type"],
        "source": item_v1.get("source", "unknown"),
        "is_multi_turn": bool(item_v1.get("is_multi_turn", False)),
        "audit_status": "pending",
        "audit_notes": "Auto-migrated from v1; needs human audit per docs/eval-strategy.md",
    }

    turns_v1 = item_v1.get("turns")
    if not isinstance(turns_v1, list) or not turns_v1:
        raise ValueError(f"item {item_v1['id']} has no turns")

    if out["is_multi_turn"]:
        out["turns"] = [_migrate_turn(t) for t in turns_v1]
    else:
        first = _migrate_turn(turns_v1[0])
        out["question"] = first["question"]
        for k, v in first.items():
            if k == "question":
                continue
            out[k] = v

    return out


def migrate(v1: dict[str, Any]) -> dict[str, Any]:
    missing = V1_REQUIRED_TOP_LEVEL - v1.keys()
    if missing:
        raise KeyError(f"v1 dataset missing top-level fields: {missing}")

    out: dict[str, Any] = {
        "schema_version": "2.0",
        "show_id": v1["show_id"],
        "show_slug": v1.get("show_slug", ""),
        "created_at": v1.get("created_at", ""),
        "migrated_from_v1": True,
        "notes": "v2 migration: see docs/eval-strategy.md. Items default to audit_status=pending; 7 audited items overlaid from chat-rag-dataset-audit-2026-05-25 case study.",
        "items": [_migrate_item(it) for it in v1["items"]],
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    v1_path = Path(args.input)
    v2_path = Path(args.output)
    v1 = json.loads(v1_path.read_text(encoding="utf-8"))

    try:
        v2 = migrate(v1)
    except (KeyError, ValueError) as e:
        print(f"[migration FAILED] {e}", file=sys.stderr)
        return 2

    v2_path.write_text(
        json.dumps(v2, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"✓ migrated {len(v2['items'])} items → {v2_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
