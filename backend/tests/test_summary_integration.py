"""Integration tests for the summary task — DB state transitions with
mocked LLM. Covers happy path (pending→running→done) and retry-exhaustion
(pending→running→failed) without writing back to transcription_queue.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.models.episode import AiSummaryStatus, Episode
from app.models.show import Show
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_segment import TranscriptSegment
from app.models.transcription_queue import QueueStatus, TranscriptionQueue

from .conftest import _postgres_reachable


@pytest_asyncio.fixture
async def episode_with_transcript():
    """Build a show + episode + transcript + 3 segments, plus a completed
    transcription_queue row. Cleanup after."""
    async with AsyncSessionFactory() as db:
        show = Show(
            title="Pipeline Integration",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()

        ep = Episode(
            show_id=show.id,
            title="Integration Episode",
            audio_url="https://example.com/a.mp3",
            guid=f"guid-{uuid.uuid4()}",
        )
        db.add(ep)
        await db.flush()

        tr = Transcript(episode_id=ep.id, status=TranscriptStatus.completed)
        db.add(tr)
        await db.flush()

        for i, txt in enumerate([
            "這是第一段逐字稿內容，說了一些開場白",
            "中間講了核心觀點，主要是關於某個主題的討論",
            "最後做了結語並預告下一集",
        ]):
            db.add(TranscriptSegment(
                transcript_id=tr.id,
                start_time=i * 10.0,
                end_time=(i + 1) * 10.0,
                text=txt,
            ))
        # Pretend transcription completed.
        db.add(TranscriptionQueue(
            episode_id=ep.id,
            show_id=show.id,
            status=QueueStatus.completed,
            position=0,
            enqueued_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            whisper_model="whisper-1",
        ))
        await db.commit()
        yield show.id, ep.id

    async with AsyncSessionFactory() as db:
        await db.execute(delete(Show).where(Show.id == show.id))
        await db.commit()


def _mock_step_config(model="gpt-test"):
    from app.services.ai_step_resolver import StepConfig
    return StepConfig(
        step_key="summary",
        step_type="chat",
        base_url="http://mock/v1",
        api_key="mock-key",
        model=model,
        extra_config={},
    )


def _mock_chat_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_pipeline_pending_to_done(episode_with_transcript):
    show_id, ep_id = episode_with_transcript

    # Mock get_step_config + the OpenAI chat completion.
    summary_text = "這集 podcast 介紹了一個主題並進行討論，內容包含開場、核心觀點分析以及結尾預告，整體節奏明確。"

    with patch(
        "app.workers.summary_task.get_step_config",
        new=AsyncMock(return_value=_mock_step_config()),
    ), patch(
        "app.services.summary_pipeline.AsyncOpenAI"
    ) as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response(summary_text)
        )
        mock_openai_cls.return_value = mock_client

        # Run the underlying _run coroutine directly (bypasses Celery's
        # asyncio.run wrapper since we're already in an async test).
        from app.workers.summary_task import _run

        fake_task = MagicMock()
        fake_task.request.retries = 0
        fake_task.max_retries = 3

        result = await _run(fake_task, str(ep_id))
        assert result == {"ok": True, "chars": len(summary_text)}

    async with AsyncSessionFactory() as db:
        ep = await db.get(Episode, ep_id)
        assert ep.ai_summary == summary_text
        assert ep.ai_summary_status == AiSummaryStatus.done.value
        assert ep.ai_summary_generated_at is not None
        assert ep.ai_summary_model == "gpt-test"

        # Crucially: transcription_queue row MUST stay completed.
        from sqlalchemy import select
        q = (await db.execute(
            select(TranscriptionQueue).where(TranscriptionQueue.episode_id == ep_id)
        )).scalar_one()
        assert q.status == QueueStatus.completed


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_pipeline_marks_failed_on_exhausted_retries(episode_with_transcript):
    """When LLM raises a transient error AND retries are exhausted, mark
    failed and re-raise (so Celery records the failure too). Transcription
    queue row must NOT be touched."""
    show_id, ep_id = episode_with_transcript

    with patch(
        "app.workers.summary_task.get_step_config",
        new=AsyncMock(return_value=_mock_step_config()),
    ), patch(
        "app.services.summary_pipeline.AsyncOpenAI"
    ) as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=httpx.ConnectError("boom")
        )
        mock_openai_cls.return_value = mock_client

        from app.workers.summary_task import _run

        fake_task = MagicMock()
        fake_task.request.retries = 3  # already at max → no more retries
        fake_task.max_retries = 3

        with pytest.raises(httpx.ConnectError):
            await _run(fake_task, str(ep_id))

    async with AsyncSessionFactory() as db:
        ep = await db.get(Episode, ep_id)
        assert ep.ai_summary is None
        assert ep.ai_summary_status == AiSummaryStatus.failed.value
        assert ep.ai_summary_generated_at is not None

        from sqlalchemy import select
        q = (await db.execute(
            select(TranscriptionQueue).where(TranscriptionQueue.episode_id == ep_id)
        )).scalar_one()
        assert q.status == QueueStatus.completed


@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
@pytest.mark.asyncio
async def test_idempotency_skips_already_done(episode_with_transcript):
    """Re-running on a row already at status=done short-circuits without LLM call."""
    show_id, ep_id = episode_with_transcript

    async with AsyncSessionFactory() as db:
        ep = await db.get(Episode, ep_id)
        ep.ai_summary = "preset"
        ep.ai_summary_status = AiSummaryStatus.done.value
        ep.ai_summary_generated_at = datetime.now(timezone.utc)
        await db.commit()

    with patch(
        "app.services.summary_pipeline.AsyncOpenAI"
    ) as mock_openai_cls:
        from app.workers.summary_task import _run

        fake_task = MagicMock()
        result = await _run(fake_task, str(ep_id))
        assert result == {"skipped": "already_done"}
        mock_openai_cls.assert_not_called()
