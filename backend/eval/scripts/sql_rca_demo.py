"""SQL RCA demo — verify eval_traces plumbing + Tier 1 RCA template.

Prints three sections of PG eval_traces output for a given --run-id:

  1. per-turn span count grouped by item_id, turn_idx, span_type
  2. (optional) cross-run search_query diff vs --compare-run-id
  3. per-turn tool timeline ordered by started_at (tool_name, elapsed_ms)

Usage:
    python -m backend.eval.scripts.sql_rca_demo \\
        --run-id eval-20260530T153012Z-a1b2c3d4 \\
        [--compare-run-id eval-20260530T160000Z-deadbeef]

For prod DB, override DATABASE_URL or run inside backend container via
`zeabur service exec`.

Per design Decision 5: ship this with the plumbing change so future Tier 1
b20 chunk-level RCA + Tier 2 retrieval changes can copy-paste this template.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / "backend" / ".env")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402


SECTION_HEADER = "=" * 70


async def _section1_per_turn_span_count(db, run_id: str) -> int:
    """Returns distinct item_id count for the run."""
    print(SECTION_HEADER)
    print(f"[1] per-turn span count for run_id = {run_id!r}")
    print(SECTION_HEADER)
    sql = text(
        """
        SELECT item_id, turn_idx, span_type, COUNT(*) AS n
        FROM eval_traces
        WHERE run_id = :run_id
        GROUP BY item_id, turn_idx, span_type
        ORDER BY item_id, turn_idx, span_type
        """
    )
    rows = (await db.execute(sql, {"run_id": run_id})).all()
    if not rows:
        print("(no rows — plumbing did not write for this run_id)")
        return 0
    print(f"{'item_id':<12} {'turn':>4} {'span_type':<12} {'n':>4}")
    print("-" * 38)
    items = set()
    for r in rows:
        items.add(r.item_id)
        print(f"{r.item_id:<12} {r.turn_idx:>4} {r.span_type:<12} {r.n:>4}")
    print(f"\ndistinct item_id = {len(items)}, total span rows = {sum(r.n for r in rows)}")
    return len(items)


async def _section2_cross_run_query_diff(
    db, run_id_old: str, run_id_new: str
) -> int:
    print(SECTION_HEADER)
    print(f"[2] search_query diff: {run_id_old!r} vs {run_id_new!r}")
    print(SECTION_HEADER)
    sql = text(
        """
        WITH old AS (
            SELECT item_id, turn_idx, tool_name, search_query
            FROM eval_traces
            WHERE run_id = :old AND search_query IS NOT NULL
        ),
        new AS (
            SELECT item_id, turn_idx, tool_name, search_query
            FROM eval_traces
            WHERE run_id = :new AND search_query IS NOT NULL
        )
        SELECT
            COALESCE(o.item_id, n.item_id)    AS item_id,
            COALESCE(o.turn_idx, n.turn_idx)  AS turn_idx,
            COALESCE(o.tool_name, n.tool_name) AS tool_name,
            o.search_query AS old_query,
            n.search_query AS new_query
        FROM old o
        FULL OUTER JOIN new n
          ON o.item_id = n.item_id
         AND o.turn_idx = n.turn_idx
         AND o.tool_name = n.tool_name
        WHERE o.search_query IS DISTINCT FROM n.search_query
        ORDER BY item_id, turn_idx, tool_name
        """
    )
    rows = (await db.execute(sql, {"old": run_id_old, "new": run_id_new})).all()
    if not rows:
        print("(no diff — every (item, turn, tool) shares identical search_query)")
        return 0
    for r in rows:
        print(
            f"  {r.item_id}/t{r.turn_idx}/{r.tool_name}\n"
            f"    old: {r.old_query!r}\n"
            f"    new: {r.new_query!r}"
        )
    print(f"\n{len(rows)} differing row(s).")
    return len(rows)


async def _section3_per_turn_tool_timeline(db, run_id: str) -> int:
    print(SECTION_HEADER)
    print(f"[3] per-turn tool timeline for run_id = {run_id!r}")
    print(SECTION_HEADER)
    sql = text(
        """
        SELECT item_id, turn_idx, span_type, tool_name, stage_name,
               elapsed_ms, started_at
        FROM eval_traces
        WHERE run_id = :run_id
        ORDER BY item_id, turn_idx, started_at
        """
    )
    rows = (await db.execute(sql, {"run_id": run_id})).all()
    if not rows:
        print("(no rows)")
        return 0
    current_key: tuple | None = None
    n = 0
    for r in rows:
        key = (r.item_id, r.turn_idx)
        if key != current_key:
            print(f"\n  --- {r.item_id} turn {r.turn_idx} ---")
            current_key = key
        label = r.tool_name or r.stage_name or r.span_type
        ms = r.elapsed_ms if r.elapsed_ms is not None else "?"
        print(f"    {r.started_at.isoformat()}  {label:<32} {ms} ms")
        n += 1
    return n


async def _run(run_id: str, compare_run_id: str | None) -> int:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            distinct = await _section1_per_turn_span_count(db, run_id)
            print()
            if compare_run_id:
                await _section2_cross_run_query_diff(db, run_id, compare_run_id)
            else:
                print(SECTION_HEADER)
                print("[2] search_query diff — skipped (no --compare-run-id)")
                print(SECTION_HEADER)
            print()
            timeline_rows = await _section3_per_turn_tool_timeline(db, run_id)
    finally:
        await engine.dispose()

    print()
    print(SECTION_HEADER)
    print(
        f"summary: distinct_items={distinct}, timeline_rows={timeline_rows}"
    )
    print(SECTION_HEADER)
    return 0 if distinct > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True, help="Primary run_id to query.")
    ap.add_argument(
        "--compare-run-id",
        default=None,
        help="Optional second run_id for cross-run search_query diff.",
    )
    args = ap.parse_args()
    return asyncio.run(_run(args.run_id, args.compare_run_id))


if __name__ == "__main__":
    sys.exit(main())
