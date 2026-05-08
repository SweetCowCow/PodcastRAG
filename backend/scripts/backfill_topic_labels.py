"""Bulk backfill `transcript_segments.topic_label` via LLM classification.

Routes through OpenAI direct (not Zeabur AI Hub) for speed + reliability.
Runs N episodes concurrently via asyncio.gather (default 5).

Usage:
    python -m backend.scripts.backfill_topic_labels --all
    python -m backend.scripts.backfill_topic_labels --episode-id <UUID>
    python -m backend.scripts.backfill_topic_labels --all --concurrency 5 --model gpt-4o-mini
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import uuid
from collections import Counter

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptStatus
from app.services.topic_segmentation import classify_episode

logger = logging.getLogger(__name__)


async def _process_one(
    Session, ep_id: uuid.UUID, client: OpenAI, model: str, idx: int, total: int
) -> tuple[int, int]:
    """Returns (segments_count, error_count). Logs progress."""
    try:
        async with Session() as session:
            label_map = await classify_episode(
                session, ep_id, client=client, model=model
            )
        dist = Counter(label_map.values())
        print(
            f"[{idx}/{total}] episode={ep_id} segments={len(label_map)} "
            f"dist={dict(dist)}",
            flush=True,
        )
        return len(label_map), 0
    except Exception:
        logger.exception("episode %s: classify failed", ep_id)
        return 0, 1


async def run(
    all_: bool, episode_id: uuid.UUID | None, concurrency: int, model: str
) -> tuple[int, int, int]:
    api_key = os.environ.get("OPENAI_API_KEY") or settings.openai_api_key
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not configured — set in env or backend/.env"
        )
    client = OpenAI(api_key=api_key)  # base_url defaults to OpenAI direct

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

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
        logger.info(
            "processing %d episodes (concurrency=%d, model=%s)",
            len(ids),
            concurrency,
            model,
        )

    sem = asyncio.Semaphore(concurrency)

    async def _bounded(idx: int, ep_id: uuid.UUID) -> tuple[int, int]:
        async with sem:
            return await _process_one(Session, ep_id, client, model, idx, len(ids))

    results = await asyncio.gather(
        *[_bounded(i + 1, ep) for i, ep in enumerate(ids)]
    )

    episodes = sum(1 for r in results if r[0] > 0)
    segments = sum(r[0] for r in results)
    errors = sum(r[1] for r in results)

    await engine.dispose()
    return episodes, segments, errors


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--episode-id", type=uuid.UUID)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--model", default="gpt-4o-mini")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    eps, segs, errs = asyncio.run(
        run(args.all, args.episode_id, args.concurrency, args.model)
    )
    print(f"summary: episodes={eps} segments={segs} errors={errs}", flush=True)
    return 0 if errs == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
