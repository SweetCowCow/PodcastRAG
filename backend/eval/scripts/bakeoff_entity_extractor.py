"""Entity extractor model bake-off — compare 3 LLMs on the golden set.

Runs `query_entity.extract_entities` against the golden set's questions
with each candidate model, collects the structured output to JSONL for
later human audit. Reports per-model success rate and observable
divergences.

Models tested (admin can swap via flags):
- gpt-4o-mini (OpenAI direct)
- gemini-2.5-flash-lite (via Zeabur AI Hub)
- claude-haiku-4-5 (via Zeabur AI Hub)

Safety:
- DRY-RUN by default: prints what would be sent + cost estimate, no API calls
- --execute: actually run; reads keys from DB via key_resolver

Output: `docs/research/entity-bakeoff-<run_id>.jsonl`, one row per
(question, model). Human audit (Phase 7.2) is a separate step that reads
this file and labels each row.

Usage:
    # Dry run — print prompts + cost estimate, no API calls
    cd backend && python -m eval.scripts.bakeoff_entity_extractor --dry-run

    # Real run, default golden set
    cd backend && python -m eval.scripts.bakeoff_entity_extractor --execute

    # Run on _pending_review.json (broader question variety) instead
    cd backend && python -m eval.scripts.bakeoff_entity_extractor --execute \
        --dataset backend/eval/datasets/_pending_review.json

Cost ceiling: --execute refuses if estimated cost > $0.50 (~30 questions
× 3 models, all cheap models ~$0.10-0.20 total realistic). Override with
--force-budget if you really want to spend more.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from backend.app.schemas.query_entity import QueryEntities  # noqa: F401
    from backend.app.services.query_entity import ExtractionStatus, extract_entities
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.schemas.query_entity import QueryEntities  # noqa: F401
    from app.services.query_entity import ExtractionStatus, extract_entities

from openai import AsyncOpenAI


@dataclass(frozen=True)
class ModelSpec:
    label: str            # Short name for output file
    model: str            # Model id passed to chat.completions
    base_url: str         # e.g. https://api.openai.com/v1
    key_env: str          # env var holding the API key
    est_cost_per_q: float # Rough USD per question for budget gating


# Default bake-off candidates. Costs are rough — actual depends on prompt size.
DEFAULT_CANDIDATES: list[ModelSpec] = [
    ModelSpec(
        label="gpt-4o-mini",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        key_env="OPENAI_OFFICIAL_KEY",
        est_cost_per_q=0.0008,
    ),
    ModelSpec(
        label="gemini-2.5-flash-lite",
        model="gemini-2.5-flash-lite",
        base_url="https://hnd1.aihub.zeabur.ai/v1",
        key_env="OPENAI_API_KEY",  # Zeabur AI Hub gateway key
        est_cost_per_q=0.0003,
    ),
    ModelSpec(
        label="claude-haiku-4-5",
        model="claude-haiku-4-5",
        base_url="https://hnd1.aihub.zeabur.ai/v1",
        key_env="OPENAI_API_KEY",
        est_cost_per_q=0.0010,
    ),
]


def _load_questions(dataset_path: Path) -> list[dict]:
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    return [{"id": it["id"], "question": it["question"], "type": it.get("type", "")} for it in items]


async def _run_one(spec: ModelSpec, api_key: str, question: str, now: datetime) -> dict:
    client = AsyncOpenAI(base_url=spec.base_url, api_key=api_key)
    entities, status = await extract_entities(
        client, model=spec.model, question=question, now=now,
    )
    return {
        "entities": entities.model_dump(mode="json"),
        "status": status.value,
    }


async def _bakeoff(
    dataset_path: Path,
    candidates: list[ModelSpec],
    keys: dict[str, str],
    out_path: Path,
) -> dict:
    questions = _load_questions(dataset_path)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")

    rows = []
    per_model_status: dict[str, dict[str, int]] = {c.label: {} for c in candidates}

    print(f"[bakeoff_entity_extractor] {len(questions)} questions × {len(candidates)} models", file=sys.stderr)
    for i, q in enumerate(questions, 1):
        for spec in candidates:
            key = keys[spec.label]
            try:
                result = await _run_one(spec, key, q["question"], now)
            except Exception as exc:  # noqa: BLE001
                # extract_entities is supposed to fail-open; this catches truly
                # uncaught surprises (e.g. wrong base_url, network).
                result = {"entities": None, "status": f"exception:{type(exc).__name__}"}
            row = {
                "run_id": run_id,
                "question_id": q["id"],
                "question_type": q["type"],
                "question": q["question"],
                "model_label": spec.label,
                "model": spec.model,
                **result,
            }
            rows.append(row)
            per_model_status[spec.label][result["status"]] = per_model_status[spec.label].get(result["status"], 0) + 1
        if i % 5 == 0:
            print(f"  progress: {i}/{len(questions)}", file=sys.stderr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return {
        "run_id": run_id,
        "n_questions": len(questions),
        "n_models": len(candidates),
        "out_path": str(out_path),
        "per_model_status": per_model_status,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bake-off entity extractor models")
    p.add_argument(
        "--dataset",
        type=Path,
        default=Path("backend/eval/datasets/this-not-that-cool.json"),
        help="Golden set JSON path",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("docs/research"),
        help="Where to write the JSONL output (gitignored)",
    )
    p.add_argument("--dry-run", action="store_true", help="Print plan + cost estimate, no API calls")
    p.add_argument("--execute", action="store_true", help="Actually call the models")
    p.add_argument(
        "--force-budget",
        action="store_true",
        help="Override the $0.50 budget guard",
    )
    return p.parse_args()


def _estimate_cost(dataset_path: Path, candidates: list[ModelSpec]) -> float:
    questions = _load_questions(dataset_path)
    return sum(spec.est_cost_per_q for spec in candidates) * len(questions)


async def _amain(args: argparse.Namespace) -> int:
    if not args.dry_run and not args.execute:
        print("ERROR: pass --dry-run or --execute", file=sys.stderr)
        return 2

    questions = _load_questions(args.dataset)
    candidates = DEFAULT_CANDIDATES

    print(f"Dataset: {args.dataset} ({len(questions)} questions)", file=sys.stderr)
    print(f"Models:  {[c.label for c in candidates]}", file=sys.stderr)

    est = _estimate_cost(args.dataset, candidates)
    print(f"Estimated cost: ~${est:.4f} total", file=sys.stderr)

    if args.dry_run:
        # Show what one prompt looks like with the first model
        from app.services.query_entity import _SYSTEM_PROMPT  # type: ignore[attr-defined]
        print("\n--- system prompt (first 200 chars) ---", file=sys.stderr)
        print(_SYSTEM_PROMPT[:200] + "...", file=sys.stderr)
        print("\n--- sample user content ---", file=sys.stderr)
        print(f"current_datetime_utc: {datetime.now(timezone.utc).isoformat()}", file=sys.stderr)
        print(f"question: {questions[0]['question']}", file=sys.stderr)
        return 0

    if est > 0.50 and not args.force_budget:
        print(f"ERROR: estimated cost ${est:.4f} > $0.50 budget; pass --force-budget to override", file=sys.stderr)
        return 2

    # Resolve API keys per model
    import os
    keys: dict[str, str] = {}
    for spec in candidates:
        k = os.environ.get(spec.key_env)
        if not k:
            print(f"ERROR: env var {spec.key_env} not set for {spec.label}", file=sys.stderr)
            return 2
        keys[spec.label] = k

    out_path = args.out_dir / f"entity-bakeoff-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    summary = await _bakeoff(args.dataset, candidates, keys, out_path)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    return asyncio.run(_amain(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
