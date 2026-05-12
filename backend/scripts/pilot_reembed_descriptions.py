"""Phase 2 pilot driver: re-chunk + re-embed episode descriptions for one show.

Two modes:
  --dry-run (default): compute chunk counts + token estimate + cost projection.
                       Prints summary, writes detail to --output JSON file.
                       Does NOT call OpenAI. Does NOT write DB.
  --execute:           actually call embedding API + INSERT new chunk rows
                       with chunking_version=2 (depends on the sibling change
                       `chunking-version-coexistence` for the schema column).
                       Resumable via --state-file.

THIS TASK ONLY EXERCISES --dry-run. Do not run --execute until:
  1. `chunking-version-coexistence` change is merged (DB schema ready).
  2. Cost estimate reviewed by a human.
  3. Backend Celery / embedding step config sanity-checked.

Usage:
    cd backend && python -m scripts.pilot_reembed_descriptions \\
        --show-id 45fc2462-17cf-42f5-98a7-68fe1a222228 \\
        --dry-run \\
        --output /tmp/pilot-cost-estimate.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.episode import Episode
from app.models.episode_description_chunk import EpisodeDescriptionChunk
from app.services import tokenizer
from app.services.ai_step_resolver import get_step_config
from app.services.description_rechunker import (
    DescriptionChunk,
    rechunk_description,
)
from app.services.embedding import embed_texts

logger = logging.getLogger(__name__)

# OpenAI text-embedding-3-small pricing (as of 2026-05): $0.02 per 1M tokens.
EMBEDDING_MODEL = "text-embedding-3-small"
USD_PER_MILLION_TOKENS = 0.02
# OpenAI baseline (from Phase 2 design.md) — used to derive a safety margin.
OPENAI_BASELINE_USD = 108.59


@dataclass
class EpisodeEstimate:
    episode_id: str
    raw_chars: int
    chunk_count: int
    total_chars: int
    tokens: int


def _count_tokens(texts: list[str]) -> int:
    """Token count via tiktoken's cl100k_base (used by text-embedding-3-small)."""
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    return sum(len(enc.encode(t)) for t in texts)


async def _load_episodes_from_db(
    show_id: uuid.UUID,
) -> list[tuple[uuid.UUID, str]]:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as s:
            rows = await s.execute(
                select(Episode.id, Episode.description)
                .where(Episode.show_id == show_id)
                .where(Episode.description.is_not(None))
                .order_by(Episode.published_at.desc().nulls_last())
            )
            return [(r[0], r[1]) for r in rows.all() if r[1]]
    finally:
        await engine.dispose()


def _load_episodes_from_json(path: Path) -> list[tuple[uuid.UUID, str]]:
    """Offline fallback for dry-run when the prod DB isn't reachable from
    the dev host. Expects a JSON array of {"id": "<uuid>", "description": "..."}.
    """
    raw = json.loads(path.read_text())
    out: list[tuple[uuid.UUID, str]] = []
    for r in raw:
        if not r.get("description"):
            continue
        out.append((uuid.UUID(r["id"]), r["description"]))
    return out


def _run_dry(
    show_id: uuid.UUID,
    episodes: list[tuple[uuid.UUID, str]],
    output_path: Path,
) -> dict:
    per_ep: list[EpisodeEstimate] = []
    sample_chunks: list[dict] = []

    for ep_id, raw in episodes:
        chunks: list[DescriptionChunk] = rechunk_description(raw)
        chunk_texts = [c.text for c in chunks]
        total_chars = sum(len(t) for t in chunk_texts)
        tokens = _count_tokens(chunk_texts) if chunk_texts else 0
        per_ep.append(
            EpisodeEstimate(
                episode_id=str(ep_id),
                raw_chars=len(raw),
                chunk_count=len(chunks),
                total_chars=total_chars,
                tokens=tokens,
            )
        )
        if len(sample_chunks) < 5 and chunks:
            for c in chunks[: 5 - len(sample_chunks)]:
                sample_chunks.append(
                    {
                        "episode_id": str(ep_id),
                        "text": c.text,
                        "chars": len(c.text),
                        "start_char": c.start_char,
                        "end_char": c.end_char,
                    }
                )

    total_chunks = sum(e.chunk_count for e in per_ep)
    total_tokens = sum(e.tokens for e in per_ep)
    estimated_usd = total_tokens * USD_PER_MILLION_TOKENS / 1_000_000
    safety_factor = (
        OPENAI_BASELINE_USD / estimated_usd if estimated_usd > 0 else float("inf")
    )

    summary = {
        "show_id": str(show_id),
        "embedding_model": EMBEDDING_MODEL,
        "usd_per_million_tokens": USD_PER_MILLION_TOKENS,
        "total_episodes": len(per_ep),
        "total_chunks": total_chunks,
        "estimated_tokens": total_tokens,
        "estimated_usd": round(estimated_usd, 6),
        "openai_baseline_usd": OPENAI_BASELINE_USD,
        "safety_factor_vs_baseline": round(safety_factor, 2),
        "avg_chunks_per_episode": (
            round(total_chunks / len(per_ep), 2) if per_ep else 0
        ),
        "sample_chunks": sample_chunks,
        "per_episode": [asdict(e) for e in per_ep],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    print("=" * 64)
    print(f"Pilot dry-run: show {show_id}")
    print("=" * 64)
    print(f"  Episodes processed     : {summary['total_episodes']}")
    print(f"  Total chunks produced  : {summary['total_chunks']}")
    print(f"  Avg chunks/episode     : {summary['avg_chunks_per_episode']}")
    print(f"  Estimated tokens       : {summary['estimated_tokens']:,}")
    print(
        f"  Estimated cost (USD)   : ${summary['estimated_usd']:.6f}  "
        f"(model: {EMBEDDING_MODEL})"
    )
    print(
        f"  Safety factor vs OpenAI baseline (${OPENAI_BASELINE_USD}): "
        f"{summary['safety_factor_vs_baseline']}x cheaper"
    )
    print(f"  Detail written to      : {output_path}")
    print("=" * 64)
    print("First few chunk samples:")
    for i, sc in enumerate(sample_chunks, 1):
        preview = sc["text"][:80].replace("\n", " ")
        print(f"  [{i}] ep={sc['episode_id'][:8]} ({sc['chars']} chars) {preview}")
    return summary


async def _run_execute(
    show_id: uuid.UUID,
    episodes: list[tuple[uuid.UUID, str]],
    state_path: Path,
) -> None:
    """Actually re-chunk + re-embed + write v2 rows into
    episode_description_chunks. Idempotent per-episode: each run first
    DELETEs any existing (episode_id, chunking_version=2) rows for that
    episode, then INSERTs fresh v2 rows numbered (0..N-1).

    Resume: writes `state_path` after every successful episode commit
    containing `{"completed": ["<episode_id>", ...]}`. Re-runs skip
    episodes already in that list.

    Depends on the `chunking-version-coexistence` schema migration
    (`t8a9b0c1d2e3`) having been applied to the target DB.
    """
    completed: set[str] = set()
    if state_path.exists():
        try:
            completed = set(json.loads(state_path.read_text()).get("completed", []))
            logger.info("resume: %d episodes already completed", len(completed))
        except Exception:
            logger.warning(
                "could not parse state file %s; starting from scratch", state_path
            )

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    total_chunks_written = 0
    episode_count = 0
    try:
        async with Session() as s:
            embedding_cfg = await get_step_config(s, "embedding")
            await tokenizer.load_dictionary(s)

            for ep_id, raw in episodes:
                ep_id_str = str(ep_id)
                if ep_id_str in completed:
                    continue

                chunks = rechunk_description(raw)
                if not chunks:
                    logger.info("episode %s: 0 chunks (empty after clean); skip", ep_id)
                    completed.add(ep_id_str)
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    state_path.write_text(
                        json.dumps({"completed": sorted(completed)}, ensure_ascii=False)
                    )
                    continue

                chunk_texts = [c.text for c in chunks]
                vectors = embed_texts(chunk_texts, embedding_cfg)
                if len(vectors) != len(chunk_texts):
                    raise RuntimeError(
                        f"embed_texts returned {len(vectors)} vectors for "
                        f"{len(chunk_texts)} chunks (episode {ep_id})"
                    )

                try:
                    # Idempotent: wipe any prior v2 rows for this episode.
                    await s.execute(
                        delete(EpisodeDescriptionChunk).where(
                            EpisodeDescriptionChunk.episode_id == ep_id,
                            EpisodeDescriptionChunk.chunking_version == 2,
                        )
                    )
                    for idx, (txt, vec) in enumerate(zip(chunk_texts, vectors)):
                        tokens = tokenizer.tokenize(txt)
                        tsv_text = " ".join(tokens)
                        stmt = pg_insert(EpisodeDescriptionChunk.__table__).values(
                            episode_id=ep_id,
                            chunking_version=2,
                            chunk_index=idx,
                            text=txt,
                            embedding=vec,
                            text_tsvector=func.to_tsvector("simple", tsv_text),
                        )
                        await s.execute(stmt)
                    await s.commit()
                    total_chunks_written += len(chunks)
                    episode_count += 1
                    completed.add(ep_id_str)
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    state_path.write_text(
                        json.dumps({"completed": sorted(completed)}, ensure_ascii=False)
                    )
                    logger.info(
                        "episode %s: wrote %d v2 chunks (total %d eps / %d chunks)",
                        ep_id, len(chunks), episode_count, total_chunks_written,
                    )
                except Exception:
                    await s.rollback()
                    logger.exception(
                        "episode %s: failed; will be retried on next run", ep_id
                    )
                    continue
    finally:
        await engine.dispose()

    print("=" * 64)
    print(f"--execute summary: show {show_id}")
    print(f"  Episodes processed this run : {episode_count}")
    print(f"  v2 chunks written this run  : {total_chunks_written}")
    print(f"  Total completed (resumable) : {len(completed)}")
    print(f"  State file                  : {state_path}")
    print("=" * 64)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--show-id", type=uuid.UUID, required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Estimate chunks + tokens + cost only (default).",
    )
    mode.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Actually call OpenAI + write DB rows. Requires "
             "chunking-version-coexistence schema.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/pilot-cost-estimate.json"),
        help="Path to write dry-run JSON detail.",
    )
    p.add_argument(
        "--state-file",
        type=Path,
        default=Path("/tmp/pilot-reembed-state.json"),
        help="Resume state for --execute (last_processed_episode_id).",
    )
    p.add_argument(
        "--descriptions-json",
        type=Path,
        default=None,
        help="Load episode descriptions from a JSON file instead of the DB "
             "(useful for dry-run when prod DB is unreachable from dev host). "
             "Format: [{\"id\": \"<uuid>\", \"description\": \"...\"}, ...]",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.descriptions_json is not None:
        episodes = _load_episodes_from_json(args.descriptions_json)
    else:
        episodes = asyncio.run(_load_episodes_from_db(args.show_id))
    if not episodes:
        print(f"No episodes with descriptions found for show {args.show_id}.")
        return 1

    if args.dry_run:
        _run_dry(args.show_id, episodes, args.output)
        return 0

    asyncio.run(_run_execute(args.show_id, episodes, args.state_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
