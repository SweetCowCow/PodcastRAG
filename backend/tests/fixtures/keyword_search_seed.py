"""Reusable fixture seed for manual keyword-search verification.

Builds one show with three episodes that exercise each section of the
keyword-search response, so a human (or browser smoke) can search the seeded
terms and confirm T1 / T2 / T3 behave:

- EP1 → T1: one chunk contains BOTH terms (馬世芳 + 滅火器) → same-chunk AND hit.
- EP2 → T2: 馬世芳 only in the title, 滅火器 only in a transcript chunk →
  cross-pool episode AND (no single chunk has both).
- EP3 → T3: chunks each contain only one term → strict T1/T2 miss for the
  two-term AND query, so an OR fallback query surfaces them.

Usage (from the `backend/` directory):

    python -m tests.fixtures.keyword_search_seed --dry-run   # list the plan
    python -m tests.fixtures.keyword_search_seed             # write to the DB

`--dry-run` prints the row counts and episode titles WITHOUT touching the DB.
"""
from __future__ import annotations

import argparse
import asyncio
import secrets

TERM_A = "馬世芳"
TERM_B = "滅火器"

# (episode title, [chunk texts]) — title may itself carry a term (EP2).
PLAN = [
    (
        "T1 同段命中：來賓專訪",
        [
            f"今天聊到 {TERM_A}，也談了 {TERM_B} 現場演出的故事",
            f"後段又回到 {TERM_A} 與 {TERM_B} 的合作",
        ],
    ),
    (
        f"T2 跨欄位命中：{TERM_A} 特集",  # 馬世芳 in title
        [
            f"這集現場演了 {TERM_B} 的歌，氣氛很好",  # 滅火器 in transcript
        ],
    ),
    (
        "T3 鬆散命中：雜談",
        [
            f"這段只提到 {TERM_A}",
            f"那段只提到 {TERM_B}",
        ],
    ),
]


def _plan_summary() -> str:
    lines = [f"Show: keyword-search 測試節目 (terms: {TERM_A}, {TERM_B})"]
    total_chunks = 0
    for title, chunks in PLAN:
        lines.append(f"  Episode: {title}  ({len(chunks)} chunks)")
        total_chunks += len(chunks)
    lines.append(f"Totals: 1 show, {len(PLAN)} episodes, {total_chunks} chunks")
    return "\n".join(lines)


async def _seed() -> dict:
    from sqlalchemy import func
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.models.episode import Episode
    from app.models.show import Show
    from app.models.transcript import Transcript, TranscriptStatus
    from app.models.transcript_chunk import TranscriptChunk
    from app.services import tokenizer

    engine = create_async_engine(settings.database_url)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    counts = {"shows": 0, "episodes": 0, "chunks": 0}

    async with Maker() as db:
        await tokenizer.load_dictionary(db)

        def _tsv(text_value: str):
            return func.to_tsvector("simple", " ".join(tokenizer.tokenize(text_value)))

        suffix = secrets.token_hex(4)
        show = Show(
            title="keyword-search 測試節目",
            rss_url=f"https://example.test/kwseed-{suffix}.rss",
            language="zh",
        )
        db.add(show)
        await db.commit()
        await db.refresh(show)
        counts["shows"] += 1

        for ep_idx, (title, chunk_texts) in enumerate(PLAN):
            ep = Episode(
                show_id=show.id,
                title=title,
                audio_url=f"https://example.test/kwseed-{suffix}-{ep_idx}.mp3",
                guid=f"kwseed-{suffix}-{ep_idx}",
                title_tsvector=_tsv(title),
            )
            db.add(ep)
            await db.commit()
            await db.refresh(ep)
            counts["episodes"] += 1

            tr = Transcript(episode_id=ep.id, status=TranscriptStatus.completed)
            db.add(tr)
            await db.commit()
            await db.refresh(tr)

            for ci, txt in enumerate(chunk_texts):
                db.add(
                    TranscriptChunk(
                        transcript_id=tr.id,
                        chunk_index=ci,
                        start_time=float(ci * 30),
                        end_time=float(ci * 30 + 29),
                        text=txt,
                        text_tsvector=_tsv(txt),
                        segment_ids=[],
                    )
                )
                counts["chunks"] += 1
            await db.commit()

        counts["show_id"] = str(show.id)

    await engine.dispose()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the seed plan (row counts + episode titles) without writing",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] would create:")
        print(_plan_summary())
        return

    counts = asyncio.run(_seed())
    print("Seeded keyword-search fixture:")
    print(
        f"  show_id={counts['show_id']}  "
        f"shows={counts['shows']} episodes={counts['episodes']} chunks={counts['chunks']}"
    )


if __name__ == "__main__":
    main()
