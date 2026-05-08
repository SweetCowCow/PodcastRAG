"""Rebuild transcript_chunks for one or all transcripts.

For each transcript:
  1. Load transcript_segments.
  2. Run the new overlap-aware chunking algorithm.
  3. DELETE existing chunks for that transcript_id.
  4. INSERT new chunks (with text_tsvector populated via jieba).
  5. Batch embed (64 chunks/call) and UPDATE embeddings.

Resilient to per-transcript failure: log error and continue to next.

Usage:
    python -m backend.scripts.rebuild_chunks --all
    python -m backend.scripts.rebuild_chunks --transcript-id <UUID>
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_chunk import TranscriptChunk
from app.models.transcript_segment import TranscriptSegment
from app.services import tokenizer
from app.services.ai_step_resolver import get_step_config
from app.services.chunking import build_chunks
from app.services.embedding import embed_texts

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64


@dataclass
class _Counts:
    transcripts: int = 0
    chunks_deleted: int = 0
    chunks_inserted: int = 0
    chunks_embedded: int = 0
    errors: int = 0


async def _rebuild_one(session, transcript_id: uuid.UUID, embedding_cfg) -> _Counts:
    counts = _Counts(transcripts=1)

    segments = (
        await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == transcript_id)
            .order_by(TranscriptSegment.start_time)
        )
    ).scalars().all()

    if not segments:
        logger.info("transcript %s: no segments, skip", transcript_id)
        return counts

    drafts = build_chunks(segments)
    if not drafts:
        logger.info("transcript %s: no chunks built", transcript_id)
        return counts

    deleted = await session.execute(
        delete(TranscriptChunk).where(
            TranscriptChunk.transcript_id == transcript_id
        )
    )
    counts.chunks_deleted = deleted.rowcount or 0

    await tokenizer.load_dictionary(session)

    new_chunks: list[TranscriptChunk] = []
    for idx, draft in enumerate(drafts):
        tokens = tokenizer.tokenize(draft.text)
        chunk = TranscriptChunk(
            transcript_id=transcript_id,
            chunk_index=idx,
            start_time=draft.start_time,
            end_time=draft.end_time,
            text=draft.text,
            segment_ids=draft.segment_ids,
        )
        chunk.text_tsvector = func.to_tsvector("simple", " ".join(tokens))
        session.add(chunk)
        new_chunks.append(chunk)
    await session.flush()
    counts.chunks_inserted = len(new_chunks)

    # Batch embed.
    texts = [c.text for c in new_chunks]
    for batch_start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch_texts = texts[batch_start : batch_start + EMBED_BATCH_SIZE]
        batch_chunks = new_chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
        vectors = embed_texts(batch_texts, embedding_cfg)
        for chunk, vec in zip(batch_chunks, vectors):
            chunk.embedding = vec
        counts.chunks_embedded += len(vectors)

    await session.commit()
    return counts


async def run(all_: bool, transcript_id: uuid.UUID | None) -> _Counts:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    totals = _Counts()
    async with Session() as session:
        embedding_cfg = await get_step_config(session, "embedding")

        if transcript_id is not None:
            ids = [transcript_id]
        else:
            rows = await session.execute(
                select(Transcript.id).where(
                    Transcript.status == TranscriptStatus.completed
                )
            )
            ids = [r[0] for r in rows.all()]

        logger.info("rebuilding chunks for %d transcripts", len(ids))

    # Open a fresh session per transcript for clean error isolation.
    for i, tid in enumerate(ids, 1):
        try:
            async with Session() as inner:
                c = await _rebuild_one(inner, tid, embedding_cfg)
            totals.transcripts += c.transcripts
            totals.chunks_deleted += c.chunks_deleted
            totals.chunks_inserted += c.chunks_inserted
            totals.chunks_embedded += c.chunks_embedded
        except Exception:
            logger.exception("transcript %s: rebuild failed", tid)
            totals.errors += 1
        if i % 10 == 0 or i == len(ids):
            print(
                f"progress {i}/{len(ids)} "
                f"deleted={totals.chunks_deleted} inserted={totals.chunks_inserted} "
                f"embedded={totals.chunks_embedded} errors={totals.errors}"
            )

    await engine.dispose()
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--transcript-id", type=uuid.UUID)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    started = time.monotonic()
    totals = asyncio.run(run(args.all, args.transcript_id))
    elapsed = time.monotonic() - started
    print(
        f"summary: transcripts={totals.transcripts} "
        f"chunks_deleted={totals.chunks_deleted} "
        f"chunks_inserted={totals.chunks_inserted} "
        f"chunks_embedded={totals.chunks_embedded} "
        f"errors={totals.errors} "
        f"elapsed={elapsed:.1f}s"
    )
    return 0 if totals.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
