"""Cleanup v1 description chunks for a single show.

Usage:
    python -m scripts.cleanup_v1_description_chunks --show-id <UUID>
    python -m scripts.cleanup_v1_description_chunks --show-id <UUID> --execute
    python -m scripts.cleanup_v1_description_chunks --show-id <UUID> --execute --force

Dry-run is the default. `--execute` actually issues DELETE statements.
`--force` skips the "every episode must have v2 first" safeguard.

Per-episode transactional: a single failed delete rolls back that episode
only; subsequent episodes still get processed.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.models.episode_description_chunk import EpisodeDescriptionChunk

logger = logging.getLogger(__name__)


@dataclass
class EpisodeCleanupStats:
    episode_id: uuid.UUID
    title: str
    v1_chunks: int
    v2_chunks: int


async def _collect_stats(
    show_id: uuid.UUID,
) -> list[EpisodeCleanupStats]:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as s:
            rows = (
                await s.execute(
                    select(
                        Episode.id,
                        Episode.title,
                        func.count(EpisodeDescriptionChunk.id).filter(
                            EpisodeDescriptionChunk.chunking_version == 1
                        ),
                        func.count(EpisodeDescriptionChunk.id).filter(
                            EpisodeDescriptionChunk.chunking_version == 2
                        ),
                    )
                    .select_from(Episode)
                    .outerjoin(
                        EpisodeDescriptionChunk,
                        EpisodeDescriptionChunk.episode_id == Episode.id,
                    )
                    .where(Episode.show_id == show_id)
                    .group_by(Episode.id, Episode.title)
                )
            ).all()
            return [
                EpisodeCleanupStats(
                    episode_id=r[0],
                    title=r[1],
                    v1_chunks=int(r[2] or 0),
                    v2_chunks=int(r[3] or 0),
                )
                for r in rows
            ]
    finally:
        await engine.dispose()


async def _execute_delete(
    stats: list[EpisodeCleanupStats],
) -> tuple[int, int]:
    """Returns (episodes_deleted, total_v1_rows_deleted)."""
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    ep_ok = 0
    rows_deleted = 0
    try:
        async with Session() as s:
            for ep in stats:
                if ep.v1_chunks == 0:
                    continue
                try:
                    res = await s.execute(
                        delete(EpisodeDescriptionChunk).where(
                            EpisodeDescriptionChunk.episode_id == ep.episode_id,
                            EpisodeDescriptionChunk.chunking_version == 1,
                        )
                    )
                    await s.commit()
                    ep_ok += 1
                    rows_deleted += res.rowcount or 0
                    logger.info(
                        "deleted v1 chunks for episode %s (%s rows)",
                        ep.episode_id,
                        res.rowcount,
                    )
                except Exception:
                    await s.rollback()
                    logger.exception(
                        "failed to delete v1 for episode %s; continuing",
                        ep.episode_id,
                    )
    finally:
        await engine.dispose()
    return ep_ok, rows_deleted


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--show-id", type=uuid.UUID, required=True)
    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually DELETE v1 rows (default: dry-run).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Skip the 'every episode must have v2 first' safeguard.",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    stats = asyncio.run(_collect_stats(args.show_id))
    if not stats:
        print(f"No episodes found for show {args.show_id}.")
        return 1

    total = len(stats)
    with_v2 = sum(1 for s in stats if s.v2_chunks > 0)
    missing_v2 = [s for s in stats if s.v2_chunks == 0]
    total_v1_rows = sum(s.v1_chunks for s in stats)

    print("=" * 64)
    print(f"Cleanup plan: show {args.show_id}")
    print("=" * 64)
    print(f"  Episodes total      : {total}")
    print(f"  Episodes with v2    : {with_v2}")
    print(f"  Episodes missing v2 : {len(missing_v2)}")
    print(f"  v1 rows to delete   : {total_v1_rows}")

    if missing_v2 and not args.force:
        print()
        print("Refusing to delete v1: some episodes have no v2 chunk yet.")
        print("Episodes missing v2:")
        for s in missing_v2[:10]:
            print(f"  - {s.episode_id}  {s.title[:60]}")
        if len(missing_v2) > 10:
            print(f"  ... and {len(missing_v2) - 10} more")
        print("Pass --force to override.")
        return 2

    if not args.execute:
        print()
        print(f"[dry-run] would delete v1 chunks for {with_v2} episodes "
              f"({total_v1_rows} rows). Re-run with --execute.")
        return 0

    ep_ok, rows_deleted = asyncio.run(_execute_delete(stats))
    print()
    print(f"Done: deleted v1 chunks across {ep_ok} episodes "
          f"({rows_deleted} rows total).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
