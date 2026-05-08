"""Build a CSV of OOV (out-of-vocabulary) candidate terms for jieba.

Scan all `transcript_segments.text` for repeated 2-5 char substrings that
jieba's default tokeniser splits into multiple tokens. Output is a curated
human-review CSV that can be fed into `import_jieba_seed.py`.

Usage:
    python -m backend.scripts.build_jieba_seed_dict --out docs/jieba_seed_candidates.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
from pathlib import Path

import jieba
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

MIN_LEN = 2
MAX_LEN = 5
MIN_OCCURRENCES = 10

CJK_RE = re.compile(r"[一-鿿]")


def _is_cjk_only(s: str) -> bool:
    return bool(s) and all(CJK_RE.match(c) for c in s)


def _splits_in_default_jieba(term: str) -> bool:
    """Return True if stock jieba breaks `term` into >1 token."""
    return len(list(jieba.cut(term, cut_all=False))) > 1


async def collect_candidates(
    out_path: Path, min_occurrences: int = MIN_OCCURRENCES
) -> int:
    """Enumerate + count + filter substrings inside Postgres (memory-bounded)."""
    engine = create_async_engine(settings.database_url)

    # Aggregation pushed down to PG. Memory is bounded by the number of
    # surviving groups (terms that meet the regex + min-count), not by the
    # raw 2-5 char windows over the whole corpus.
    sql = """
    WITH bounds AS (
        SELECT s.text AS body, e.title
        FROM transcript_segments s
        JOIN transcripts t ON t.id = s.transcript_id
        JOIN episodes e ON e.id = t.episode_id
        WHERE s.text IS NOT NULL AND length(s.text) >= 2
    ),
    expanded AS (
        SELECT substring(b.body FROM i FOR l) AS sub, b.title
        FROM bounds b
        CROSS JOIN generate_series(2, 5) AS l
        CROSS JOIN LATERAL generate_series(1, GREATEST(length(b.body) - l + 1, 0)) AS i
    ),
    cjk_only AS (
        SELECT sub, title
        FROM expanded
        WHERE sub ~ '^[一-鿿]+$'
    )
    SELECT sub,
           COUNT(*) AS occurrences,
           (array_agg(DISTINCT title))[1:3] AS sample_titles
    FROM cjk_only
    GROUP BY sub
    HAVING COUNT(*) >= :min_occurrences
    ORDER BY COUNT(*) DESC
    """

    rows: list[tuple[str, int, list[str]]] = []
    async with engine.connect() as conn:
        result = await conn.execute(
            sa_text(sql), {"min_occurrences": min_occurrences}
        )
        for row in result.all():
            rows.append((row[0], int(row[1]), list(row[2] or [])))
    await engine.dispose()

    # Apply the jieba-splits filter on the (much smaller) candidate list.
    candidates = []
    for term, count, titles in rows:
        if not _splits_in_default_jieba(term):
            continue
        candidates.append((term, count, titles))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["term", "occurrences", "sample_episode_titles"])
        for term, count, titles in candidates:
            writer.writerow([term, count, " | ".join(titles[:3])])

    return len(candidates)


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument(
        "--out",
        default="docs/jieba_seed_candidates.csv",
        type=Path,
    )
    parser.add_argument("--min-occurrences", type=int, default=MIN_OCCURRENCES)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    n = asyncio.run(collect_candidates(args.out, args.min_occurrences))
    print(f"wrote {n} candidates to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
