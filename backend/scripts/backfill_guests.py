"""One-shot backfill: extract guests from episode titles via regex.

For every Episode (or a single show / single episode subset), run
`extract_guests_from_title(episode.title)` and UPDATE episodes.guests
with the result. Idempotent — running twice produces the same result.

Usage:
    # Backfill all episodes across all shows
    python -m backend.scripts.backfill_guests --all

    # Single show
    python -m backend.scripts.backfill_guests --show-id <SHOW_UUID>

    # Dry run — print proposed changes without writing
    python -m backend.scripts.backfill_guests --all --dry-run

    # Single episode (handy for debugging)
    python -m backend.scripts.backfill_guests --episode-id <EP_UUID>

Progress is printed every 100 episodes. Errors on a single row do not
stop the script — they are logged and counted.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.services.rss_parser import extract_guests_from_title

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill episodes.guests via title regex")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="Process every episode in the database")
    target.add_argument("--show-id", type=str, help="Limit to a single show UUID")
    target.add_argument("--episode-id", type=str, help="Limit to a single episode UUID")
    p.add_argument("--dry-run", action="store_true", help="Print what would change; do not commit")
    p.add_argument("--progress-every", type=int, default=100, help="Print a heartbeat every N rows (default 100)")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    engine = create_async_engine(settings.database_url)
    Maker = async_sessionmaker(engine, expire_on_commit=False)

    async with Maker() as session:
        stmt = select(Episode.id, Episode.title, Episode.guests).order_by(Episode.created_at)
        if args.show_id:
            stmt = stmt.where(Episode.show_id == uuid.UUID(args.show_id))
        elif args.episode_id:
            stmt = stmt.where(Episode.id == uuid.UUID(args.episode_id))

        rows = (await session.execute(stmt)).all()
        total = len(rows)
        print(f"[backfill_guests] {total} episode(s) to inspect", file=sys.stderr)
        if total == 0:
            return 0

        changed = 0
        unchanged = 0
        seen = 0
        for ep_id, title, current_guests in rows:
            seen += 1
            new_guests = extract_guests_from_title(title or "")
            if new_guests == list(current_guests or []):
                unchanged += 1
            else:
                changed += 1
                if args.dry_run:
                    print(f"  [dry] {ep_id} {title[:60]!r}: {current_guests} → {new_guests}")
                else:
                    await session.execute(
                        update(Episode)
                        .where(Episode.id == ep_id)
                        .values(guests=new_guests)
                    )

            if seen % args.progress_every == 0:
                print(
                    f"[backfill_guests] progress: {seen}/{total}; changed={changed} unchanged={unchanged}",
                    file=sys.stderr,
                )

        if not args.dry_run:
            await session.commit()

    print(
        f"[backfill_guests] done: total={total} changed={changed} unchanged={unchanged}"
        + (" (dry-run, no writes)" if args.dry_run else ""),
        file=sys.stderr,
    )
    await engine.dispose()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
