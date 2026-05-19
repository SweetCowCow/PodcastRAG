"""Generic prototype runner: framework name -> run golden set -> dump results.

Usage:
  cd backend && python -m scripts.agentic_bakeoff.runner.run_prototype <framework>

Where <framework> is one of: a_native_openai / b_pydantic_ai / e_google_adk
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from .metric_runner import dump_result, run_golden_set


SHOW_ID = uuid.UUID("45fc2462-17cf-42f5-98a7-68fe1a222228")
GOLDEN_PATH = Path(__file__).parent.parent / "golden_set" / "bakeoff_40.json"
RESULTS_DIR = Path(__file__).parent.parent / "results"


def _make_adapter(framework: str):
    if framework == "a_native_openai":
        from ..prototypes.a_native_openai.agent import NativeOpenAIAdapter
        return NativeOpenAIAdapter()
    if framework == "b_pydantic_ai":
        from ..prototypes.b_pydantic_ai.agent import PydanticAIAdapter
        return PydanticAIAdapter()
    if framework == "e_google_adk":
        from ..prototypes.e_google_adk.agent import GoogleADKAdapter
        return GoogleADKAdapter()
    raise SystemExit(f"unknown framework: {framework}")


async def amain(framework: str) -> None:
    adapter = _make_adapter(framework)
    print(f"=== running {framework} against {GOLDEN_PATH.name} ===")
    result = await run_golden_set(adapter, GOLDEN_PATH, SHOW_ID)
    out_path = dump_result(result, RESULTS_DIR)
    print(f"WROTE: {out_path}")
    agg = result.aggregate()
    print("aggregate:")
    for k, v in agg.items():
        print(f"  {k}: {v}")


def main():
    fw = sys.argv[1] if len(sys.argv) > 1 else "a_native_openai"
    asyncio.run(amain(fw))


if __name__ == "__main__":
    main()
