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
from collections import Counter, defaultdict
from pathlib import Path

import jieba
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.models.transcript import Transcript
from app.models.transcript_segment import TranscriptSegment

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
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    counter: Counter[str] = Counter()
    sample_titles: dict[str, set[str]] = defaultdict(set)

    async with Session() as session:
        result = await session.execute(
            select(TranscriptSegment.text, Episode.title)
            .join(Transcript, TranscriptSegment.transcript_id == Transcript.id)
            .join(Episode, Transcript.episode_id == Episode.id)
        )
        for text, episode_title in result.all():
            if not text:
                continue
            for length in range(MIN_LEN, MAX_LEN + 1):
                for i in range(len(text) - length + 1):
                    sub = text[i : i + length]
                    if not _is_cjk_only(sub):
                        continue
                    counter[sub] += 1
                    if len(sample_titles[sub]) < 3 and episode_title:
                        sample_titles[sub].add(episode_title)

    await engine.dispose()

    # Filter: keep only those that (a) >= min_occurrences and (b) split by stock jieba
    candidates = []
    for term, count in counter.most_common():
        if count < min_occurrences:
            break
        if not _splits_in_default_jieba(term):
            continue
        candidates.append((term, count, sorted(sample_titles[term])))

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
