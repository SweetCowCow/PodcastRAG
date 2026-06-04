"""Tests for the detection-backfill driver (EQ2e F6).

Spec: asr-homophone-detection → Requirement
"Detection backfill over a show's existing episodes".

Seeds a show + 3 episodes/transcripts against real Postgres, monkeypatches
`detect_homophones` so one episode raises, and asserts the driver is fail-open:
processed=3, failed=1, and the other two episodes' candidates are persisted.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.services import asr_detection_backfill, asr_homophone
from app.services.asr_correction import CorrectionRule
from tests.conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no local Postgres"
)


@pytest_asyncio.fixture
async def seeded_show_three_episodes(db_session):
    """Seed one show + 3 episodes, each with a transcript whose content marks
    the episode index, so a monkeypatched detector can branch per episode."""
    from app.models.asr_correction_term import AsrCorrectionTerm
    from app.models.episode import Episode
    from app.models.show import Show
    from app.models.transcript import Transcript, TranscriptStatus

    suffix = uuid.uuid4().hex[:6]
    show = Show(title=f"pytest-det-{suffix}", rss_url=f"https://e.com/{suffix}.rss")
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    ep_ids = []
    for i in range(3):
        ep = Episode(
            show_id=show.id,
            guid=f"pytest-det-{suffix}-ep{i}",
            title=f"pytest-det-{suffix} EP{i}",
            audio_url=f"https://e.com/{suffix}-{i}.mp3",
        )
        db_session.add(ep)
        await db_session.commit()
        await db_session.refresh(ep)
        db_session.add(
            Transcript(
                episode_id=ep.id,
                status=TranscriptStatus.completed,
                content=f"episode-{i} 內容",
            )
        )
        await db_session.commit()
        ep_ids.append(ep.id)

    yield {"show_id": show.id, "episode_ids": ep_ids, "suffix": suffix}

    from sqlalchemy import delete

    await db_session.execute(
        delete(AsrCorrectionTerm).where(AsrCorrectionTerm.show_id == show.id)
    )
    for ep_id in ep_ids:
        await db_session.execute(
            delete(Transcript).where(Transcript.episode_id == ep_id)
        )
        await db_session.execute(delete(Episode).where(Episode.id == ep_id))
    await db_session.execute(delete(Show).where(Show.id == show.id))
    await db_session.commit()


async def test_backfill_fail_open_one_episode(
    db_session, seeded_show_three_episodes, monkeypatch
):
    """Episode 1 detection raises → counted as failed, batch continues, and the
    other two episodes' candidates are persisted."""

    async def fake_detect(session, transcript_text, **kwargs):
        if "episode-1" in transcript_text:
            raise RuntimeError("boom on episode 1")
        # episode-0 → 錯0/正0 ; episode-2 → 錯2/正2 (distinct wrongs persist)
        idx = "0" if "episode-0" in transcript_text else "2"
        return [CorrectionRule(wrong=f"錯{idx}", correct=f"正{idx}")]

    monkeypatch.setattr(asr_homophone, "detect_homophones", fake_detect)
    # Skip the real candidate-entity query result mattering; driver passes it
    # through to the (faked) detector anyway.
    monkeypatch.setattr(
        asr_homophone, "load_candidate_entities", _AsyncReturn([])
    )

    report = await asr_detection_backfill.run_detection_backfill(
        db_session, seeded_show_three_episodes["show_id"]
    )

    assert report["processed"] == 3
    assert report["total"] == 3
    assert len(report["failed_episode_ids"]) == 1
    assert report["persisted"] == 2  # episodes 0 and 2 each persist one candidate


async def test_backfill_progress_callback_increments(
    db_session, seeded_show_three_episodes, monkeypatch
):
    """progress_cb fires once per episode with a monotonically rising current."""

    async def fake_detect(session, transcript_text, **kwargs):
        return []

    monkeypatch.setattr(asr_homophone, "detect_homophones", fake_detect)
    monkeypatch.setattr(
        asr_homophone, "load_candidate_entities", _AsyncReturn([])
    )

    seen: list[tuple[int, int]] = []
    await asr_detection_backfill.run_detection_backfill(
        db_session,
        seeded_show_three_episodes["show_id"],
        progress_cb=lambda cur, total, failed: seen.append((cur, total)),
    )

    assert seen == [(1, 3), (2, 3), (3, 3)]


class _AsyncReturn:
    """Callable returning a fixed value from an awaitable (monkeypatch helper)."""

    def __init__(self, value):
        self._value = value

    async def __call__(self, *args, **kwargs):
        return self._value
