"""Build the episode_description_chunks index in bulk or per-episode.

Usage:
    python -m backend.scripts.build_description_index --all
    python -m backend.scripts.build_description_index --episode-id <UUID>
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.services.description_indexer import build_description_index_for_episode

logger = logging.getLogger(__name__)

BATCH_SIZE = 64
MAX_RATE_LIMIT_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0


async def _process_episode_with_retry(
    session, episode_id: uuid.UUID
) -> str:
    from openai import RateLimitError

    delay = BASE_BACKOFF_SECONDS
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            return await build_description_index_for_episode(session, episode_id)
        except RateLimitError:
            if attempt >= MAX_RATE_LIMIT_RETRIES - 1:
                logger.error("episode %s: rate-limit retries exhausted", episode_id)
                return "error"
            logger.warning(
                "episode %s rate-limited, retry in %.1fs", episode_id, delay
            )
            time.sleep(delay)
            delay *= 2
        except Exception:
            logger.exception("episode %s: unexpected error", episode_id)
            return "error"
    return "error"


async def run(all_: bool, episode_id: uuid.UUID | None) -> tuple[int, int, int, int]:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    inserts = updates = skips = errors = 0

    async with Session() as session:
        if episode_id is not None:
            ids = [episode_id]
        else:
            rows = await session.execute(
                select(Episode.id).where(Episode.description.is_not(None))
            )
            ids = [r[0] for r in rows.all()]
        total = len(ids)
        logger.info("processing %d episodes (batch_size=%d)", total, BATCH_SIZE)

        for batch_start in range(0, total, BATCH_SIZE):
            batch = ids[batch_start : batch_start + BATCH_SIZE]
            batch_inserts = batch_updates = batch_skips = batch_errors = 0
            for ep_id in batch:
                outcome = await _process_episode_with_retry(session, ep_id)
                if outcome == "inserted":
                    inserts += 1
                    batch_inserts += 1
                elif outcome == "updated":
                    updates += 1
                    batch_updates += 1
                elif outcome in ("skipped", "deleted_empty"):
                    skips += 1
                    batch_skips += 1
                else:
                    errors += 1
                    batch_errors += 1
            print(
                f"batch {batch_start // BATCH_SIZE + 1}: "
                f"inserts={batch_inserts} updates={batch_updates} "
                f"skips={batch_skips} errors={batch_errors}"
            )

    await engine.dispose()
    return inserts, updates, skips, errors


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--episode-id", type=uuid.UUID)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    inserts, updates, skips, errors = asyncio.run(run(args.all, args.episode_id))
    print(
        f"summary: inserts={inserts} updates={updates} "
        f"skips={skips} errors={errors}"
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
