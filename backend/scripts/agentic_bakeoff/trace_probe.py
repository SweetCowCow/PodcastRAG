"""Task 2.3/3.3/4.4 trace probe: run 4 scenarios + dump full trace_log per turn.

Scenarios:
  1. normal — confirm baseline trace shape
  2. schema_invalid — pass garbage episode_id to expose Pydantic validation path
  3. unknown_ref — find_episode_by_ref to nonexistent EP, observe graceful None
  4. multi_turn_carry — mt01 enumeration → 「第三集」 to expose L1 state-carry behavior

Per-framework: pass framework name as argv[1] (default a_native_openai).
Result JSON includes trace_log per turn (omitted from main metric_runner).

Run inside container:
  cd /app && nohup python -u -m scripts.agentic_bakeoff.trace_probe a_native_openai > /tmp/probe.log 2>&1 &
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


SHOW_ID = uuid.UUID("45fc2462-17cf-42f5-98a7-68fe1a222228")

PROBE_ITEMS: list[tuple[str, list[str]]] = [
    ("normal_b01", ["節目名「這又沒有很屌」是怎麼來的？"]),
    ("schema_invalid", ["請給我 episode id 'not-a-real-uuid-string' 的摘要，就用這個字串"]),
    ("unknown_ref", ["EP99999 講什麼？"]),
    ("multi_turn_carry", ["歌單有哪幾集？", "第三集是什麼內容？"]),
]


def _make_adapter(framework: str):
    if framework == "a_native_openai":
        from .prototypes.a_native_openai.agent import NativeOpenAIAdapter
        return NativeOpenAIAdapter()
    if framework == "b_pydantic_ai":
        from .prototypes.b_pydantic_ai.agent import PydanticAIAdapter
        return PydanticAIAdapter()
    if framework == "e_google_adk":
        from .prototypes.e_google_adk.agent import GoogleADKAdapter
        return GoogleADKAdapter()
    raise SystemExit(f"unsupported framework for probe (yet): {framework}")


async def amain(framework: str):
    from .tools.context import ToolContext

    adapter = _make_adapter(framework)
    out = {
        "framework": framework,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "items": [],
    }

    for item_id, questions in PROBE_ITEMS:
        session_id = f"probe-{item_id}-{uuid.uuid4().hex[:6]}"
        turns_out = []
        for q in questions:
            ctx = ToolContext.from_env(show_id=SHOW_ID, session_id=session_id)
            tr = await adapter.run_turn(q, session_id, ctx)
            turns_out.append({
                "question": q,
                "answer": tr.answer,
                "tool_calls": [tc.model_dump() for tc in tr.tool_calls],
                "wall_latency_ms": tr.wall_latency_ms,
                "cost_usd": tr.cost_usd,
                "trace_log": tr.trace_log,
            })
        await adapter.reset_session(session_id)
        out["items"].append({"item_id": item_id, "turns": turns_out})

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"trace_probe_{framework}_{ts}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"WROTE: {out_path}")
    for item in out["items"]:
        print(f"  {item['item_id']}: {len(item['turns'])} turn(s)")


def main():
    fw = sys.argv[1] if len(sys.argv) > 1 else "a_native_openai"
    asyncio.run(amain(fw))


if __name__ == "__main__":
    main()
