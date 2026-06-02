"""One-off pilot driver for LLM homophone detection (EQ2b, change
asr-llm-homophone-postprocess).

Detection is normally wired into the transcription pipeline. Existing
transcripts have no standalone trigger (full backfill is a deliberate
Non-Goal), so this script lets us run a small, controlled pilot against prod
WITHOUT re-transcribing — it reuses the tested service functions
`estimate_detection_cost`, `detect_homophones`, and `persist_candidates`.

Run inside the Zeabur backend container (where settings.database_url resolves
to prod and the asr_homophone step + OpenAI key are configured):

  # 1) dry-run cost estimate (no LLM, no writes)
  python -m scripts.homophone_pilot --episodes <id1,id2,...> --dry-run

  # 2) real detection: produces pending candidates in prod
  python -m scripts.homophone_pilot --episodes <ids> --run

  # 3) synthetic recall vs the 6 EQ2a known typos (reverse-corrupt → detect),
  #    read-only — never writes candidates
  python -m scripts.homophone_pilot --episodes <ids> --synthetic-recall

Model A/B (RAGEC works with any chat model; try AI Hub models):
  python -m scripts.homophone_pilot --episodes <ids> --synthetic-recall \\
      --aihub --model qwen-3-235b
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.api_key import ApiKey
from app.models.episode import Episode
from app.models.transcript import Transcript
from app.services import asr_homophone
from app.services.asr_correction import CorrectionRule, apply_corrections

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("homophone_pilot")

KNOWN_PAIRS = [
    ("杜忠祐", "杜宗祐"),
    ("阿鳴", "阿名"),
    ("阿明", "阿名"),
    ("方品龍", "方品融"),
    ("龍虎報", "龍虎豹"),
    ("咪有企", "滅火器"),
]


def _parse_episode_ids(raw: str) -> list[uuid.UUID]:
    return [uuid.UUID(x.strip()) for x in raw.split(",") if x.strip()]


async def _build_client(session, args) -> tuple[OpenAI | None, str | None]:
    """Resolve (client, model) for an A/B run. --aihub routes via the Zeabur AI
    Hub key + base_url; otherwise None,None lets detect_homophones use the step
    config. --model overrides the model name in either case."""
    if not args.aihub and not args.model:
        return None, None
    if args.aihub:
        key = (
            await session.execute(
                select(ApiKey).where(ApiKey.provider == "zeabur-aihub")
            )
        ).scalars().first()
        base = "https://hnd1.aihub.zeabur.ai/v1"
        if key is None:
            raise RuntimeError("no zeabur-aihub api key found")
        return OpenAI(base_url=base, api_key=key.api_key), args.model
    # --model without --aihub: use the configured openai key/base, swap model.
    from app.services.ai_step_resolver import get_step_config

    cfg = await get_step_config(session, asr_homophone.ASR_HOMOPHONE_STEP_KEY)
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key), args.model


async def _load_transcript(session, ep_id: uuid.UUID):
    content = (
        await session.execute(
            select(Transcript.content).where(Transcript.episode_id == ep_id)
        )
    ).scalar_one_or_none()
    show_id = (
        await session.execute(
            select(Episode.show_id).where(Episode.id == ep_id)
        )
    ).scalar_one_or_none()
    return content, show_id


async def run_dry_run(session, episode_ids) -> None:
    est = await asr_homophone.estimate_detection_cost(session, episode_ids)
    print("=== DRY-RUN COST ESTIMATE (no LLM, no writes) ===")
    print(f"episodes with transcript : {est.episode_count}")
    print(f"total chars              : {est.total_chars}")
    print(f"estimated input tokens   : {est.estimated_input_tokens}")
    print(f"estimated cost (USD)     : ${est.estimated_cost_usd}")
    if est.missing_transcript_ids:
        print(f"missing transcript ids   : {est.missing_transcript_ids}")


async def run_detection(session, episode_ids, client, model) -> None:
    print(f"=== REAL DETECTION (model={model or 'step-default'}) ===")
    grand_total = 0
    for ep_id in episode_ids:
        content, show_id = await _load_transcript(session, ep_id)
        if not content or show_id is None:
            print(f"[{ep_id}] no transcript/show — skipped")
            continue
        pairs = await asr_homophone.detect_homophones(
            session, content, show_id=show_id, client=client, model=model
        )
        print(f"[{ep_id}] detected {len(pairs)} pair(s):")
        for p in pairs:
            print(f"    {p.wrong} -> {p.correct}")
        inserted = await asr_homophone.persist_candidates(
            session, pairs, show_id=show_id
        )
        print(f"    persisted {inserted} new candidate(s)")
        grand_total += inserted
    print(f"TOTAL new candidates persisted: {grand_total}")


async def run_synthetic_recall(session, episode_ids, client, model) -> None:
    print(f"=== SYNTHETIC RECALL vs 6 EQ2a known typos (model={model or 'step-default'}) ===")
    contents: dict[uuid.UUID, tuple[str, uuid.UUID]] = {}
    for ep_id in episode_ids:
        content, show_id = await _load_transcript(session, ep_id)
        if content and show_id is not None:
            contents[ep_id] = (content, show_id)

    recovered = 0
    tested = 0
    for wrong, correct in KNOWN_PAIRS:
        target = next(
            (eid for eid, (c, _) in contents.items() if correct in c), None
        )
        if target is None:
            print(f"[{wrong}->{correct}] no pilot episode contains '{correct}' — skipped")
            continue
        tested += 1
        content, show_id = contents[target]
        corrupted = apply_corrections(content, [CorrectionRule(correct, wrong)])
        pairs = await asr_homophone.detect_homophones(
            session, corrupted, show_id=show_id, client=client, model=model
        )
        hit = any(p.wrong == wrong and p.correct == correct for p in pairs)
        also = [f"{p.wrong}->{p.correct}" for p in pairs]
        recovered += 1 if hit else 0
        print(
            f"[{wrong}->{correct}] ep={target} recovered={'YES' if hit else 'NO'} "
            f"(detector returned {len(pairs)}: {also})"
        )
    if tested:
        print(f"RECALL vs known: {recovered}/{tested} = {recovered / tested:.0%}")
    else:
        print("RECALL: no known pairs testable on these episodes")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--model", default=None, help="override model name (A/B)")
    ap.add_argument("--aihub", action="store_true", help="route via Zeabur AI Hub")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--synthetic-recall", action="store_true")
    args = ap.parse_args()

    episode_ids = _parse_episode_ids(args.episodes)
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as session:
            if args.dry_run:
                await run_dry_run(session, episode_ids)
                return
            client, model = await _build_client(session, args)
            if args.run:
                await run_detection(session, episode_ids, client, model)
            else:
                await run_synthetic_recall(session, episode_ids, client, model)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
