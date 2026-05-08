"""Bulk backfill `transcript_segments.topic_label` via LLM classification.

Default routes through OpenAI direct. Pass --base-url + --api-key-env to
route via Zeabur AI Hub or any OpenAI-compatible endpoint.

Usage:
    python -m backend.scripts.backfill_topic_labels --all
    python -m backend.scripts.backfill_topic_labels --episode-id <UUID>
    python -m backend.scripts.backfill_topic_labels --all --concurrency 10 --model gpt-4o-mini

A/B comparison (no DB writes):
    python -m backend.scripts.backfill_topic_labels --limit 5 \\
        --model gemini-2.5-flash-lite \\
        --base-url https://hnd1.aihub.zeabur.ai/v1 \\
        --api-key-env ZEABUR_API_KEY \\
        --concurrency 1 --delay-s 5 --dry-run --out /tmp/ab_gemini.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
import uuid
from collections import Counter
from pathlib import Path

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptStatus

logger = logging.getLogger(__name__)


async def _process_one(
    Session,
    ep_id: uuid.UUID,
    client: OpenAI,
    model: str,
    idx: int,
    total: int,
    *,
    dry_run: bool,
    out_handle,
) -> tuple[int, int, dict]:
    """Returns (segments_count, error_count, label_map). Logs progress."""
    from app.services.topic_segmentation import (
        classify_episode,
        classify_episode_no_persist,
    )

    try:
        async with Session() as session:
            if dry_run:
                label_map = await classify_episode_no_persist(
                    session, ep_id, client=client, model=model
                )
            else:
                label_map = await classify_episode(
                    session, ep_id, client=client, model=model
                )
        dist = Counter(label_map.values())
        print(
            f"[{idx}/{total}] episode={ep_id} segments={len(label_map)} "
            f"dist={dict(dist)}",
            flush=True,
        )
        if out_handle is not None:
            out_handle.write(
                json.dumps(
                    {
                        "episode_id": str(ep_id),
                        "model": model,
                        "label_map": {str(k): v for k, v in label_map.items()},
                        "distribution": dict(dist),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            out_handle.flush()
        return len(label_map), 0, label_map
    except Exception:
        logger.exception("episode %s: classify failed", ep_id)
        return 0, 1, {}


async def run(
    *,
    all_: bool,
    episode_id: uuid.UUID | None,
    concurrency: int,
    model: str,
    base_url: str | None,
    api_key_env: str,
    limit: int | None,
    delay_s: float,
    dry_run: bool,
    out_path: Path | None,
) -> tuple[int, int, int]:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        # Fall back to OPENAI_API_KEY from settings if env not set
        if api_key_env == "OPENAI_API_KEY":
            api_key = settings.openai_api_key
    if not api_key:
        raise RuntimeError(f"{api_key_env} not configured")

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    engine = create_async_engine(
        settings.database_url,
        pool_size=concurrency + 5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        if episode_id is not None:
            ids = [episode_id]
        else:
            rows = await session.execute(
                select(Episode.id)
                .join(Transcript, Transcript.episode_id == Episode.id)
                .where(Transcript.status == TranscriptStatus.completed)
                .order_by(Episode.published_at.desc().nullslast())
            )
            ids = [r[0] for r in rows.all()]
            if limit is not None:
                ids = ids[:limit]
        logger.info(
            "processing %d episodes (concurrency=%d, model=%s, base_url=%s, dry_run=%s)",
            len(ids),
            concurrency,
            model,
            base_url or "(OpenAI default)",
            dry_run,
        )

    out_handle = None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_handle = out_path.open("w", encoding="utf-8")

    sem = asyncio.Semaphore(concurrency)

    async def _bounded(idx: int, ep_id: uuid.UUID) -> tuple[int, int, dict]:
        async with sem:
            r = await _process_one(
                Session,
                ep_id,
                client,
                model,
                idx,
                len(ids),
                dry_run=dry_run,
                out_handle=out_handle,
            )
            if delay_s > 0:
                await asyncio.sleep(delay_s)
            return r

    results = await asyncio.gather(
        *[_bounded(i + 1, ep) for i, ep in enumerate(ids)]
    )

    episodes = sum(1 for r in results if r[0] > 0)
    segments = sum(r[0] for r in results)
    errors = sum(r[1] for r in results)

    if out_handle:
        out_handle.close()
    await engine.dispose()
    return episodes, segments, errors


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--episode-id", type=uuid.UUID)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint base url. Default = OpenAI direct.",
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="Env var name holding the API key. Default OPENAI_API_KEY.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--delay-s",
        type=float,
        default=0.0,
        help="Sleep N seconds between episodes (concurrency=1 only meaningful).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not UPDATE DB; only classify + log/write to --out file.",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    started = time.monotonic()
    eps, segs, errs = asyncio.run(
        run(
            all_=args.all,
            episode_id=args.episode_id,
            concurrency=args.concurrency,
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            limit=args.limit,
            delay_s=args.delay_s,
            dry_run=args.dry_run,
            out_path=args.out,
        )
    )
    elapsed = time.monotonic() - started
    print(
        f"summary: episodes={eps} segments={segs} errors={errs} elapsed={elapsed:.1f}s",
        flush=True,
    )
    return 0 if errs == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
