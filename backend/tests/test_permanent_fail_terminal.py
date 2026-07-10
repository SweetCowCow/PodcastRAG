"""worker-reliability D1: permanent-fail finalizes state before (and despite)
failure-log recording.

Spec: task-failure-monitoring → Requirement "Permanent errors short-circuit
Celery retry" (modified). Drives `_run` with a permanent error injected at the
audio-download step (subprocess.CalledProcessError — the EP326 ffmpeg case)
and asserts:

1. transcript ends `failed` + queue row is finalized `failed` even when
   `record_task_failure` itself raises (the 2026-07-10 NameError regression
   class), and no exception escapes `_run`.
2. on the happy recording path, `record_task_failure` receives
   `retry_count=0` (module-level coroutine has no Celery task context).
"""
from __future__ import annotations

import subprocess
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from tests.conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no local Postgres"
)


@pytest_asyncio.fixture
async def seeded_episode(db_session):
    from app.models.episode import Episode
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    show = Show(
        title=f"pytest-permfail-{suffix}",
        rss_url=f"https://e.com/{suffix}.rss",
        language="zh",
    )
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    ep = Episode(
        show_id=show.id,
        guid=f"pytest-permfail-{suffix}-ep",
        title=f"pytest-permfail-{suffix} EP1",
        audio_url=f"https://e.com/{suffix}.mp3",
        audio_storage_key=f"fake/{suffix}.mp3",
    )
    db_session.add(ep)
    await db_session.commit()
    await db_session.refresh(ep)

    yield {"episode_id": str(ep.id), "ep_uuid": ep.id}

    from app.models.transcript import Transcript

    await db_session.execute(
        delete(Transcript).where(Transcript.episode_id == ep.id)
    )
    await db_session.execute(delete(Episode).where(Episode.id == ep.id))
    await db_session.execute(delete(Show).where(Show.id == show.id))
    await db_session.commit()


def _patch_permanent_failure(monkeypatch):
    """Make `_run` hit a PERMANENT_ERRORS member at the download step."""
    from app.workers import tasks

    monkeypatch.setattr(
        tasks, "_is_queue_cancelled", AsyncMock(return_value=False)
    )
    mark_finished = AsyncMock()
    monkeypatch.setattr(tasks, "_mark_queue_finished", mark_finished)

    def _boom(key):
        raise subprocess.CalledProcessError(234, ["ffmpeg", "-i", key])

    monkeypatch.setattr(tasks.storage, "download_to_temp", _boom)
    return mark_finished


async def _transcript_status(db_session, ep_uuid):
    from app.models.transcript import Transcript

    tr = (
        await db_session.execute(
            select(Transcript).where(Transcript.episode_id == ep_uuid)
        )
    ).scalar_one()
    await db_session.refresh(tr)
    return tr.status


async def test_state_finalized_even_when_recording_raises(
    db_session, seeded_episode, monkeypatch
):
    from app.models.transcript import TranscriptStatus
    from app.models.transcription_queue import QueueStatus
    from app.workers import tasks

    mark_finished = _patch_permanent_failure(monkeypatch)
    monkeypatch.setattr(
        tasks,
        "record_task_failure",
        MagicMock(side_effect=RuntimeError("recording layer broke")),
    )

    result = await tasks._run(seeded_episode["episode_id"])

    assert result["status"] == "failed"
    status = await _transcript_status(db_session, seeded_episode["ep_uuid"])
    assert status == TranscriptStatus.failed
    mark_finished.assert_awaited_once()
    args = mark_finished.await_args.args
    assert args[0] == seeded_episode["ep_uuid"]
    assert args[1] == QueueStatus.failed


async def test_recording_receives_retry_count_zero(
    db_session, seeded_episode, monkeypatch
):
    from app.models.transcript import TranscriptStatus
    from app.workers import tasks

    _patch_permanent_failure(monkeypatch)
    recorder = MagicMock()
    monkeypatch.setattr(tasks, "record_task_failure", recorder)

    result = await tasks._run(seeded_episode["episode_id"])

    assert result["status"] == "failed"
    recorder.assert_called_once()
    assert recorder.call_args.kwargs["retry_count"] == 0
    status = await _transcript_status(db_session, seeded_episode["ep_uuid"])
    assert status == TranscriptStatus.failed
