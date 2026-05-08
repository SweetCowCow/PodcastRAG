"""Import a curated jieba seed dictionary CSV into `tokenizer_custom_terms`.

Usage:
    python -m backend.scripts.import_jieba_seed --csv docs/jieba_seed_curated.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.tokenizer_term import TokenizerCustomTerm

logger = logging.getLogger(__name__)


async def import_from_csv(
    csv_path: Path, default_weight: int = 100, source: str = "seed_script"
) -> tuple[int, int]:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    inserted = 0
    skipped = 0
    async with Session() as session:
        existing = {
            row[0]
            for row in (
                await session.execute(select(TokenizerCustomTerm.term))
            ).all()
        }

        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                term = (row.get("term") or "").strip()
                if not term:
                    continue
                if term in existing:
                    skipped += 1
                    logger.info("skip duplicate: %s", term)
                    continue
                weight_raw = (row.get("weight") or "").strip()
                weight = int(weight_raw) if weight_raw else default_weight
                session.add(
                    TokenizerCustomTerm(term=term, weight=weight, source=source)
                )
                existing.add(term)
                inserted += 1
        await session.commit()

    await engine.dispose()
    return inserted, skipped


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--source", default="seed_script")
    parser.add_argument("--default-weight", type=int, default=100)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    inserted, skipped = asyncio.run(
        import_from_csv(args.csv, args.default_weight, args.source)
    )
    print(f"inserted={inserted} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
