"""Bulk backfill `transcript_segments.topic_label` via LLM classification.

Usage:
    python -m backend.scripts.backfill_topic_labels --all
    python -m backend.scripts.backfill_topic_labels --episode-id <UUID>
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptStatus
from app.services.topic_segmentation import classify_episode

logger = logging.getLogger(__name__)


async def run(all_: bool, episode_id: uuid.UUID | None) -> tuple[int, int, int]:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    episodes = 0
    segments = 0
    errors = 0

    async with Session() as session:
        if episode_id is not None:
            ids = [episode_id]
        else:
            rows = await session.execute(
                select(Episode.id)
                .join(Transcript, Transcript.episode_id == Episode.id)
                .where(Transcript.status == TranscriptStatus.completed)
            )
            ids = [r[0] for r in rows.all()]
        logger.info("processing %d episodes", len(ids))

    for i, ep_id in enumerate(ids, 1):
        try:
            async with Session() as inner:
                label_map = await classify_episode(inner, ep_id)
            episodes += 1
            segments += len(label_map)
            dist = Counter(label_map.values())
            print(
                f"[{i}/{len(ids)}] episode={ep_id} segments={len(label_map)} "
                f"dist={dict(dist)}"
            )
        except Exception:
            logger.exception("episode %s: classify failed", ep_id)
            errors += 1

    await engine.dispose()
    return episodes, segments, errors


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--episode-id", type=uuid.UUID)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    eps, segs, errs = asyncio.run(run(args.all, args.episode_id))
    print(f"summary: episodes={eps} segments={segs} errors={errs}")
    return 0 if errs == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
