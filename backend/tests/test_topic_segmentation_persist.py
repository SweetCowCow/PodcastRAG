"""Integration tests for per-batch commit + skip_labelled in classify_episode.

Locks in the v5 backfill safety net: a process killed mid-episode must
preserve the labels it has already committed (one batch at a time), so
the next run can resume on the remaining NULL segments without re-paying
LLM cost on the already-classified ones.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionFactory
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_segment import TranscriptSegment
from app.services import topic_segmentation as ts

from .conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="postgres not reachable"
)


@pytest_asyncio.fixture
async def episode_with_70_segments():
    """Build an episode with 70 segments → 3 LLM batches (30+30+10)."""
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Persist Test",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()

        ep = Episode(
            show_id=show.id,
            title="70-seg",
            audio_url="https://example.com/a.mp3",
            guid=f"guid-{uuid.uuid4()}",
        )
        db.add(ep)
        await db.flush()

        tr = Transcript(episode_id=ep.id, status=TranscriptStatus.completed)
        db.add(tr)
        await db.flush()

        seg_ids = []
        for i in range(70):
            seg_id = uuid.uuid4()
            seg_ids.append(seg_id)
            db.add(TranscriptSegment(
                id=seg_id,
                transcript_id=tr.id,
                start_time=i * 10.0,
                end_time=(i + 1) * 10.0,
                text=f"段落 {i}",
            ))
        await db.commit()
        yield show.id, ep.id, seg_ids

    async with AsyncSessionFactory() as db:
        await db.execute(delete(Show).where(Show.id == show.id))
        await db.commit()


def _make_label_response(seg_ids: list[uuid.UUID], label: str = "topic_main"):
    """Build a fake OpenAI chat completion response labelling each seg."""
    body = {"labels": [{"id": str(sid), "label": label} for sid in seg_ids]}
    msg = MagicMock()
    msg.content = json.dumps(body, ensure_ascii=False)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _fake_client():
    client = MagicMock()
    client.chat.completions.with_raw_response.create = MagicMock()
    return client


@db_required
@pytest.mark.asyncio
async def test_per_batch_commit_persists_partial_on_crash(
    episode_with_70_segments,
):
    """Simulate a crash after batch 2 finishes. The first 60 segments must
    have topic_label populated; the remaining 10 must still be NULL."""
    _show_id, ep_id, seg_ids = episode_with_70_segments
    client = _fake_client()
    call_count = {"n": 0}

    def _side_effect(**kwargs):
        call_count["n"] += 1
        n = call_count["n"]
        if n == 3:
            raise RuntimeError("simulated mid-episode crash on batch 3")
        # Decode payload to figure out which seg_ids belong to this batch.
        msg_user = kwargs["messages"][1]["content"]
        payload = json.loads(msg_user)
        batch_ids = [uuid.UUID(s["id"]) for s in payload["segments"]]
        raw = _make_label_response(batch_ids, label="topic_main")
        wrapped = MagicMock()
        wrapped.headers = {}
        wrapped.parse.return_value = raw
        return wrapped

    client.chat.completions.with_raw_response.create.side_effect = _side_effect

    async with AsyncSessionFactory() as db:
        with pytest.raises(RuntimeError, match="simulated"):
            await ts.classify_episode(
                db, ep_id, client=client, model="gpt-4o-mini"
            )

    # Verify: first 60 are labelled (committed), last 10 still NULL.
    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(
                select(TranscriptSegment.id, TranscriptSegment.topic_label)
                .where(TranscriptSegment.id.in_(seg_ids))
            )
        ).all()
        labelled = sum(1 for _, lbl in rows if lbl is not None)
        unlabelled = sum(1 for _, lbl in rows if lbl is None)
        assert labelled == 60, f"expected 60 committed batch-1+2, got {labelled}"
        assert unlabelled == 10


@db_required
@pytest.mark.asyncio
async def test_skip_labelled_only_processes_null_segments(
    episode_with_70_segments,
):
    """When skip_labelled=True, segments whose topic_label is already set
    are excluded from the LLM call entirely (no re-pay)."""
    _show_id, ep_id, seg_ids = episode_with_70_segments

    # Pre-label first 50 segments to simulate a previous partial run.
    async with AsyncSessionFactory() as db:
        for sid in seg_ids[:50]:
            await db.execute(
                TranscriptSegment.__table__.update()
                .where(TranscriptSegment.id == sid)
                .values(topic_label="intro")
            )
        await db.commit()

    client = _fake_client()
    seen_ids: list[uuid.UUID] = []

    def _side_effect(**kwargs):
        msg_user = kwargs["messages"][1]["content"]
        payload = json.loads(msg_user)
        batch_ids = [uuid.UUID(s["id"]) for s in payload["segments"]]
        seen_ids.extend(batch_ids)
        raw = _make_label_response(batch_ids, label="topic_main")
        wrapped = MagicMock()
        wrapped.headers = {}
        wrapped.parse.return_value = raw
        return wrapped

    client.chat.completions.with_raw_response.create.side_effect = _side_effect

    async with AsyncSessionFactory() as db:
        await ts.classify_episode(
            db, ep_id, client=client, model="gpt-4o-mini", skip_labelled=True
        )

    # The LLM only ever saw segments 50-69 (the previously-NULL ones).
    assert set(seen_ids) == set(seg_ids[50:]), (
        "skip_labelled must exclude already-labelled segments from LLM input"
    )

    # Pre-existing labels are untouched (still 'intro', not overwritten).
    async with AsyncSessionFactory() as db:
        rows = dict(
            (r[0], r[1]) for r in (
                await db.execute(
                    select(TranscriptSegment.id, TranscriptSegment.topic_label)
                    .where(TranscriptSegment.id.in_(seg_ids))
                )
            ).all()
        )
        for sid in seg_ids[:50]:
            assert rows[sid] == "intro"
        for sid in seg_ids[50:]:
            assert rows[sid] == "topic_main"
