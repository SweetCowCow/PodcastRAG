"""R3.3 Phase 8 follow-up: populate `episodes.title_tsvector` for rows whose
column is currently NULL (or `--all` to re-tokenise every row).

The original Phase 1 migration added the column as plain `tsvector NULL` —
no Python hook wrote into it, so prod ended up with 164/164 NULL rows and
the new title pool was a dead pool. This script does a one-off backfill;
new episodes inserted from this commit onward populate via
`app.services.sync._title_tsv_expr` / `app.api.shows._title_tsv_expr`.

Usage::

    # only NULL rows, all shows
    python -m backend.scripts.backfill_title_tsv

    # specific show only
    python -m backend.scripts.backfill_title_tsv --show-id 45fc2462-…

    # re-tokenise every row (use after tokenizer dict changes)
    python -m backend.scripts.backfill_title_tsv --all

    # dry-run: print would-write counts, no commit
    python -m backend.scripts.backfill_title_tsv --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.services import tokenizer


async def _run(*, show_id: uuid.UUID | None, all_rows: bool, dry_run: bool) -> None:
    engine = create_async_engine(settings.database_url)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with Maker() as db:
        await tokenizer.load_dictionary(db)

        q = select(Episode.id, Episode.title)
        if show_id is not None:
            q = q.where(Episode.show_id == show_id)
        if not all_rows:
            q = q.where(Episode.title_tsvector.is_(None))
        rows = (await db.execute(q)).all()

        print(
            f"backfill_title_tsv: {len(rows)} episodes to process "
            f"(show_id={show_id} all={all_rows} dry_run={dry_run})"
        )

        written = 0
        for i, (eid, title) in enumerate(rows, 1):
            tsv_text = tokenizer.title_tsv_text(title)
            if dry_run:
                if i <= 5:
                    print(f"  [dry] {eid} title={title!r} tokens={tsv_text!r}")
                continue
            await db.execute(
                update(Episode)
                .where(Episode.id == eid)
                .values(title_tsvector=func.to_tsvector("simple", tsv_text))
            )
            written += 1
            if i % 50 == 0:
                await db.commit()
                print(f"  progress: {i}/{len(rows)} committed")

        if not dry_run:
            await db.commit()
        print(f"backfill_title_tsv: done. updated={written} dry_run={dry_run}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--show-id", type=str, default=None, help="UUID; default: all shows")
    p.add_argument("--all", action="store_true", help="re-tokenise every row, not just NULL ones")
    p.add_argument("--dry-run", action="store_true", help="report counts, do not write")
    args = p.parse_args()
    show_id = uuid.UUID(args.show_id) if args.show_id else None
    asyncio.run(_run(show_id=show_id, all_rows=args.all, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
