"""Detection backfill over a show's existing episodes (EQ2e F6).

Part of change `asr-homophone-full-backfill`. Drives homophone DETECTION (not
application) across every existing transcript of one show, reusing the
established RAGEC path: `load_candidate_entities` → `detect_homophones` →
`persist_candidates`. It ONLY produces pending candidates; it never changes any
transcript text (the apply path stays gated behind human approval).

Design contract (see design.md):
- D1: runs as a dedicated background job off a service driver; does NOT touch
  the transcription queue.
- D-A: sequential by default (one episode at a time). Concurrency is a possible
  later optimisation but is intentionally not implemented here — 565 sequential
  text-only calls take minutes, and concurrency would pressure the AI Hub rate
  limit and DB session.
- Fail-open per episode: a single episode's detection/persist failure is logged,
  counted, and skipped — the batch continues with the remaining episodes.
- The candidate-entity list is loaded once for the show and reused across every
  episode (it is show-scoped, not episode-scoped) to avoid N redundant queries.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable
from uuid import UUID

from sqlalchemy import select

from app.services import asr_homophone

if TYPE_CHECKING:
    from openai import OpenAI
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Progress callback: (current, total, failed_episode_ids) → None. The Celery
# task wraps this to emit update_state; in tests it captures the call sequence.
ProgressCb = Callable[[int, int, list[str]], None]


async def run_detection_backfill(
    session: "AsyncSession",
    show_id: UUID,
    *,
    progress_cb: ProgressCb | None = None,
    client: "OpenAI | None" = None,
    model: str | None = None,
    instruction: str | None = None,
) -> dict:
    """Run homophone detection over every existing transcript of ``show_id``.

    Iterates the show's episodes that have transcript content; per episode it
    detects homophone pairs (RAGEC, grounded on the show's candidate entities)
    and persists them as pending, disabled, show-scoped candidates. Detection
    NEVER changes transcript text.

    Per-episode fail-open: a detection or persist error for one episode is
    logged, the episode is counted as failed, and the batch continues. Returns
    ``{processed, total, persisted, failed_episode_ids}`` where ``processed`` is
    every episode attempted (success + failed) and ``persisted`` is the total
    NEW candidates inserted across the show (deduped by `persist_candidates`).

    ``client``/``model``/``instruction`` are injectable for tests / model A/B;
    when omitted `detect_homophones` resolves them from the `asr_homophone` step.
    """
    from app.models.episode import Episode
    from app.models.transcript import Transcript

    rows = (
        await session.execute(
            select(Episode.id, Transcript.content)
            .join(Transcript, Transcript.episode_id == Episode.id)
            .where(Episode.show_id == show_id, Transcript.content.isnot(None))
            .order_by(Episode.published_at, Episode.id)
        )
    ).all()
    episodes = [(ep_id, content) for ep_id, content in rows if content and content.strip()]
    total = len(episodes)

    # Load the candidate-entity list once for the show (show-scoped, not
    # per-episode) so detection over N episodes does not re-query N times.
    candidate_entities = await asr_homophone.load_candidate_entities(session, show_id)

    processed = 0
    persisted = 0
    failed_episode_ids: list[str] = []

    for ep_id, content in episodes:
        try:
            pairs = await asr_homophone.detect_homophones(
                session,
                content,
                show_id=show_id,
                candidate_entities=candidate_entities,
                client=client,
                model=model,
                instruction=instruction,
            )
            persisted += await asr_homophone.persist_candidates(
                session, pairs, show_id=show_id
            )
        except Exception:
            logger.warning(
                "asr detection backfill: episode %s failed; skipping (fail-open)",
                ep_id,
                exc_info=True,
            )
            failed_episode_ids.append(str(ep_id))
        processed += 1
        if progress_cb is not None:
            progress_cb(processed, total, list(failed_episode_ids))

    logger.info(
        "asr detection backfill: show %s done — processed=%d/%d persisted=%d failed=%d",
        show_id,
        processed,
        total,
        persisted,
        len(failed_episode_ids),
    )
    return {
        "processed": processed,
        "total": total,
        "persisted": persisted,
        "failed_episode_ids": failed_episode_ids,
    }
