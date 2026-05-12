"""r3-4 Section 6: backfill `embedding_v2` for the entire corpus.

Targets two tables:
  - transcript_chunks (largest, ~111k rows)
  - episode_description_chunks (~3-6k rows after r3-4 max=120 re-chunk)

Modes:
  --dry-run (default): scan rows missing embedding_v2, sample texts,
                       compute token estimate + USD cost projection.
                       Does NOT call OpenAI. Writes detail to --report.
  --execute:           actually embed via text-embedding-3-large and
                       UPDATE the embedding_v2 column for every row
                       where it's currently NULL. Resumable via
                       --state-file (per-row id checkpoint, batched).

Rate limit / cost guards:
  - Hard budget ceiling: --budget-usd (default $5). Abort before exceeding.
  - Token-per-minute soft throttle (configurable, default 2.5M TPM to stay
    well under OpenAI Tier 3's 3M TPM ceiling).
  - Batch size 64 texts per OpenAI call (max v3-large supports is 100s of
    inputs but smaller batches survive partial failures gracefully).

Resumability:
  - State file format: {"transcript_done_ids": [...], "desc_done_ids": [...]}
  - Re-runs skip ids already in state. Each batch commit appends ids.
  - Crash-safe: state file written after every successful commit.

Usage (production, via Zeabur):
  # 1. Dry-run cost estimate
  python -m scripts.backfill_embedding_v2 --dry-run --report /tmp/r34-cost.json

  # 2. Execute (background, persistent)
  nohup stdbuf -oL python3 -u -m scripts.backfill_embedding_v2 \
      --execute --state-file /tmp/r34-backfill.state \
      > /tmp/r34-backfill.log 2>&1 &
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services.ai_step_resolver import get_step_config
from app.services.embedding import (
    EMBEDDING_BATCH_SIZE,
    V2_EMBEDDING_DIM,
    V2_EMBEDDING_MODEL,
    embed_texts_v2,
)

logger = logging.getLogger(__name__)

# text-embedding-3-large pricing (2026-05): $0.13 per 1M tokens.
USD_PER_MILLION_TOKENS = 0.13


@dataclass
class BackfillStats:
    transcript_rows: int = 0
    transcript_done: int = 0
    desc_rows: int = 0
    desc_done: int = 0
    tokens_total: int = 0
    usd_spent: float = 0.0
    elapsed_s: float = 0.0


def _count_tokens(texts: list[str]) -> int:
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    return sum(len(enc.encode(t)) for t in texts)


def _load_state(path: Path | None) -> dict:
    if path and path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            logger.warning("state file %s unparseable; starting fresh", path)
    return {"transcript_done_ids": [], "desc_done_ids": []}


def _save_state(path: Path | None, state: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


async def _dry_run(
    report_path: Path, sample_n: int
) -> dict:
    """Scan rows missing embedding_v2; compute token count + cost projection.

    Samples up to `sample_n` rows per table for token counting (the actual
    text size is the cost driver; we extrapolate from sample to total).
    """
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    out: dict = {"transcript_chunks": {}, "episode_description_chunks": {}}
    try:
        async with Session() as s:
            # transcript_chunks
            total_q = sql_text(
                "SELECT COUNT(*) FROM transcript_chunks "
                "WHERE embedding_v2 IS NULL"
            )
            total = (await s.execute(total_q)).scalar() or 0
            sample_q = sql_text(
                "SELECT text FROM transcript_chunks "
                "WHERE embedding_v2 IS NULL "
                "ORDER BY id LIMIT :n"
            )
            sample_texts = [
                r[0]
                for r in (await s.execute(sample_q, {"n": sample_n})).all()
                if r[0]
            ]
            sample_tokens = _count_tokens(sample_texts) if sample_texts else 0
            est_tokens = (
                int(sample_tokens * total / len(sample_texts))
                if sample_texts
                else 0
            )
            out["transcript_chunks"] = {
                "rows_missing": total,
                "sample_size": len(sample_texts),
                "sample_tokens": sample_tokens,
                "avg_tokens_per_row": (
                    round(sample_tokens / len(sample_texts), 2)
                    if sample_texts
                    else 0
                ),
                "estimated_tokens_total": est_tokens,
                "estimated_usd": round(
                    est_tokens * USD_PER_MILLION_TOKENS / 1_000_000, 4
                ),
            }

            # episode_description_chunks
            total_q = sql_text(
                "SELECT COUNT(*) FROM episode_description_chunks "
                "WHERE embedding_v2 IS NULL"
            )
            total = (await s.execute(total_q)).scalar() or 0
            sample_q = sql_text(
                "SELECT text FROM episode_description_chunks "
                "WHERE embedding_v2 IS NULL "
                "ORDER BY id LIMIT :n"
            )
            sample_texts = [
                r[0]
                for r in (await s.execute(sample_q, {"n": sample_n})).all()
                if r[0]
            ]
            sample_tokens = _count_tokens(sample_texts) if sample_texts else 0
            est_tokens = (
                int(sample_tokens * total / len(sample_texts))
                if sample_texts
                else 0
            )
            out["episode_description_chunks"] = {
                "rows_missing": total,
                "sample_size": len(sample_texts),
                "sample_tokens": sample_tokens,
                "avg_tokens_per_row": (
                    round(sample_tokens / len(sample_texts), 2)
                    if sample_texts
                    else 0
                ),
                "estimated_tokens_total": est_tokens,
                "estimated_usd": round(
                    est_tokens * USD_PER_MILLION_TOKENS / 1_000_000, 4
                ),
            }
    finally:
        await engine.dispose()

    out["model"] = V2_EMBEDDING_MODEL
    out["dim"] = V2_EMBEDDING_DIM
    out["usd_per_million_tokens"] = USD_PER_MILLION_TOKENS
    out["estimated_usd_total"] = round(
        out["transcript_chunks"]["estimated_usd"]
        + out["episode_description_chunks"]["estimated_usd"],
        4,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print("=" * 60)
    print(f"r3-4 backfill dry-run (model: {V2_EMBEDDING_MODEL})")
    print("=" * 60)
    for tbl, d in (
        ("transcript_chunks", out["transcript_chunks"]),
        ("episode_description_chunks", out["episode_description_chunks"]),
    ):
        print(f"  {tbl}:")
        print(f"    rows_missing            : {d['rows_missing']:,}")
        print(f"    avg_tokens_per_row      : {d['avg_tokens_per_row']}")
        print(f"    estimated_tokens_total  : {d['estimated_tokens_total']:,}")
        print(f"    estimated_usd           : ${d['estimated_usd']}")
    print(f"  TOTAL estimated cost: ${out['estimated_usd_total']}")
    print(f"  report -> {report_path}")
    return out


async def _backfill_table(
    table: str,
    state_key: str,
    state: dict,
    state_path: Path | None,
    embedding_cfg,
    stats: BackfillStats,
    budget_usd: float,
    tpm_limit: int,
    batch_size: int,
) -> None:
    """Generic backfill loop for one chunk table.

    Picks rows where embedding_v2 IS NULL AND id NOT IN done_set, in id
    order, batches of `batch_size`, embeds, UPDATEs by id, commits, and
    appends ids to state.
    """
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    done_set: set[str] = set(state.get(state_key, []))
    minute_start = time.monotonic()
    tokens_this_minute = 0
    try:
        async with Session() as s:
            while True:
                # Pull next batch of NULL ids + texts.
                q = sql_text(
                    f"SELECT id, text FROM {table} "
                    f"WHERE embedding_v2 IS NULL "
                    f"ORDER BY id LIMIT :n"
                )
                rows = (await s.execute(q, {"n": batch_size})).all()
                if not rows:
                    break
                # Filter out ids already in state (defensive — should be 0
                # after the UPDATE commits but a crash between commit and
                # state write would leave duplicates).
                rows = [r for r in rows if str(r[0]) not in done_set]
                if not rows:
                    break

                ids = [r[0] for r in rows]
                texts = [r[1] or "" for r in rows]
                batch_tokens = _count_tokens(texts)
                batch_usd = batch_tokens * USD_PER_MILLION_TOKENS / 1_000_000

                # Budget guard.
                if stats.usd_spent + batch_usd > budget_usd:
                    print(
                        f"BUDGET STOP: would spend ${stats.usd_spent + batch_usd:.4f} "
                        f"exceeds --budget-usd ${budget_usd}",
                        flush=True,
                    )
                    return

                # TPM throttle (rolling 60s window).
                now = time.monotonic()
                if now - minute_start >= 60:
                    minute_start = now
                    tokens_this_minute = 0
                if tokens_this_minute + batch_tokens > tpm_limit:
                    sleep_s = 60 - (now - minute_start) + 1
                    print(
                        f"TPM throttle: sleeping {sleep_s:.1f}s "
                        f"(would exceed {tpm_limit} TPM)",
                        flush=True,
                    )
                    await asyncio.sleep(sleep_s)
                    minute_start = time.monotonic()
                    tokens_this_minute = 0

                # Embed.
                t0 = time.monotonic()
                try:
                    vectors = await asyncio.to_thread(
                        embed_texts_v2, texts, embedding_cfg
                    )
                except Exception as exc:
                    print(
                        f"embed failed (batch {len(rows)} rows, table {table}): "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    # Skip this batch by marking ids done WITHOUT writing
                    # embedding_v2 — they'll be picked up on next dry-run /
                    # next run; we don't want infinite retry on poison rows.
                    # Conservative: just abort, operator inspects.
                    raise

                # UPDATE rows by id.
                for row_id, vec in zip(ids, vectors):
                    # pgvector expects '[1,2,...]' literal via str.
                    vec_lit = "[" + ",".join(repr(float(x)) for x in vec) + "]"
                    await s.execute(
                        sql_text(
                            f"UPDATE {table} SET embedding_v2 = "
                            f"CAST(:vec AS vector) WHERE id = :id"
                        ),
                        {"vec": vec_lit, "id": row_id},
                    )
                await s.commit()

                # Update state + stats.
                done_set.update(str(i) for i in ids)
                state[state_key] = sorted(done_set)
                _save_state(state_path, state)
                stats.tokens_total += batch_tokens
                stats.usd_spent += batch_usd
                tokens_this_minute += batch_tokens
                if table == "transcript_chunks":
                    stats.transcript_done += len(rows)
                else:
                    stats.desc_done += len(rows)

                elapsed = time.monotonic() - t0
                print(
                    f"[{table}] batch={len(rows)} tokens={batch_tokens} "
                    f"usd_so_far=${stats.usd_spent:.4f} "
                    f"transcript_done={stats.transcript_done} "
                    f"desc_done={stats.desc_done} "
                    f"batch_s={elapsed:.1f}",
                    flush=True,
                )
    finally:
        await engine.dispose()


async def _run_execute(
    state_path: Path,
    budget_usd: float,
    tpm_limit: int,
    batch_size: int,
) -> None:
    state = _load_state(state_path)
    stats = BackfillStats()
    t0 = time.monotonic()

    # Resolve embedding step config once (api_key + base_url).
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as s:
            embedding_cfg = await get_step_config(s, "embedding")
    finally:
        await engine.dispose()

    # Count total rows missing for progress reporting.
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as s:
            r = await s.execute(
                sql_text(
                    "SELECT COUNT(*) FROM transcript_chunks "
                    "WHERE embedding_v2 IS NULL"
                )
            )
            stats.transcript_rows = r.scalar() or 0
            r = await s.execute(
                sql_text(
                    "SELECT COUNT(*) FROM episode_description_chunks "
                    "WHERE embedding_v2 IS NULL"
                )
            )
            stats.desc_rows = r.scalar() or 0
    finally:
        await engine.dispose()

    print(
        f"START execute: transcript_missing={stats.transcript_rows} "
        f"desc_missing={stats.desc_rows} budget=${budget_usd} "
        f"tpm_limit={tpm_limit} batch_size={batch_size}",
        flush=True,
    )

    # Backfill descriptions first (small, fast feedback).
    await _backfill_table(
        "episode_description_chunks",
        "desc_done_ids",
        state,
        state_path,
        embedding_cfg,
        stats,
        budget_usd,
        tpm_limit,
        batch_size,
    )
    # Then transcripts (bulk).
    await _backfill_table(
        "transcript_chunks",
        "transcript_done_ids",
        state,
        state_path,
        embedding_cfg,
        stats,
        budget_usd,
        tpm_limit,
        batch_size,
    )

    stats.elapsed_s = time.monotonic() - t0
    print(
        f"DONE execute: transcript_done={stats.transcript_done}/"
        f"{stats.transcript_rows} desc_done={stats.desc_done}/{stats.desc_rows} "
        f"tokens={stats.tokens_total} usd=${stats.usd_spent:.4f} "
        f"elapsed_s={stats.elapsed_s:.0f}",
        flush=True,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Estimate tokens + cost only (default).",
    )
    mode.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Actually embed + UPDATE rows.",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path("/tmp/r34-backfill-dry-run.json"),
        help="Dry-run cost report output JSON.",
    )
    p.add_argument(
        "--state-file",
        type=Path,
        default=Path("/tmp/r34-backfill.state"),
        help="Resume state file (--execute).",
    )
    p.add_argument(
        "--budget-usd",
        type=float,
        default=5.0,
        help="Hard cost ceiling. Backfill aborts before exceeding.",
    )
    p.add_argument(
        "--tpm-limit",
        type=int,
        default=2_500_000,
        help="Soft tokens-per-minute throttle (stay under OpenAI tier limit).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=EMBEDDING_BATCH_SIZE,
        help="Rows per OpenAI embed call.",
    )
    p.add_argument(
        "--sample-n",
        type=int,
        default=200,
        help="Sample size per table for dry-run token estimate.",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.dry_run:
        asyncio.run(_dry_run(args.report, args.sample_n))
        return 0

    asyncio.run(
        _run_execute(
            args.state_file, args.budget_usd, args.tpm_limit, args.batch_size
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
