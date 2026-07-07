"""external-transcript-bulk-import: endpoint + import task scenarios.

Spec: external-transcript-import — admin endpoint validation (202 / 422 /
404 / 409 / auth), queue row provenance (create / revive with `external:`
label), idempotent re-import overwrite, and downstream-failure handling
(transcript failed, no partial chunks). External I/O (embedding / LLM
homophone / chain enqueues) is mocked following the transcribe-hook test
conventions; DB writes hit the real local Postgres.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionFactory
from app.main import app

from .conftest import _postgres_reachable, csrf_headers

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no local Postgres"
)

EXTERNAL_LABEL = "external:faster-whisper-large-v3-turbo"


def _payload(**over):
    p = {
        "model": "faster-whisper-large-v3-turbo",
        "language": "zh",
        "text": "今天聊滅火器的歌，還有下週的演唱會。",
        "segments": [
            {"start": 0.0, "end": 3.0, "text": "今天聊滅火器的歌，"},
            {"start": 3.0, "end": 6.5, "text": "還有下週的演唱會。"},
        ],
    }
    p.update(over)
    return p


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_episode():
    """Show + episode without transcript/queue rows; cleans up all artifacts."""
    from app.models.episode import Episode
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionFactory() as db:
        show = Show(
            title=f"pytest-import-{suffix}",
            rss_url=f"https://e.com/{suffix}.rss",
            language="zh",
        )
        db.add(show)
        await db.flush()
        ep = Episode(
            show_id=show.id,
            guid=f"pytest-import-{suffix}-ep",
            title=f"pytest-import-{suffix} EP1",
            audio_url=f"https://e.com/{suffix}.mp3",
        )
        db.add(ep)
        await db.commit()
        show_id, ep_id = show.id, ep.id

    yield {"episode_id": str(ep_id), "ep_uuid": ep_id, "show_id": show_id}

    from app.models.episode import Episode
    from app.models.show import Show
    from app.models.transcript import Transcript
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment
    from app.models.transcription_queue import TranscriptionQueue

    async with AsyncSessionFactory() as db:
        tr = (
            await db.execute(
                select(Transcript).where(Transcript.episode_id == ep_id)
            )
        ).scalar_one_or_none()
        if tr is not None:
            await db.execute(
                delete(TranscriptChunk).where(
                    TranscriptChunk.transcript_id == tr.id
                )
            )
            await db.execute(
                delete(TranscriptSegment).where(
                    TranscriptSegment.transcript_id == tr.id
                )
            )
            await db.execute(delete(Transcript).where(Transcript.id == tr.id))
        await db.execute(
            delete(TranscriptionQueue).where(
                TranscriptionQueue.episode_id == ep_id
            )
        )
        await db.execute(delete(Episode).where(Episode.id == ep_id))
        await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


def _patch_import_externals(monkeypatch):
    """Patch external I/O used by `_persist_transcription_result` so the
    import task runs offline; DB writes and correction logic stay real."""
    from app.services.ai_step_resolver import StepConfig
    from app.workers import tasks

    monkeypatch.setattr(
        tasks,
        "get_step_config",
        AsyncMock(
            side_effect=lambda s, k: StepConfig(
                step_key=k,
                step_type=k,
                base_url="https://x",
                api_key="sk-fake",
                model="fake-model",
                extra_config={},
            )
        ),
    )
    monkeypatch.setattr(
        tasks.asr_homophone, "detect_homophones", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        tasks,
        "embed_texts_dual",
        lambda texts, cfg: (
            [[0.1] * 1536 for _ in texts],
            [[0.2] * 3072 for _ in texts],
        ),
    )
    monkeypatch.setattr(
        tasks.tokenizer, "load_dictionary", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(tasks.tokenizer, "tokenize", lambda t: list(t))


async def _run_import_task(episode_id: str, payload: dict) -> dict:
    """Run the celery task eagerly in a worker thread (the task body calls
    asyncio.run, which is illegal inside the test's running loop)."""
    from app.workers.import_task import import_external_transcript

    def _apply():
        return import_external_transcript.apply(
            args=[episode_id, payload]
        ).result

    with patch(
        "app.workers.summary_task.generate_episode_summary.delay"
    ) as mock_summary, patch(
        "app.workers.topic_task.classify_episode_topics.delay"
    ) as mock_topic:
        result = await asyncio.to_thread(_apply)
    return result, mock_summary, mock_topic


async def _load_artifacts(ep_uuid):
    from app.models.transcript import Transcript
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment
    from app.models.transcription_queue import TranscriptionQueue

    async with AsyncSessionFactory() as db:
        tr = (
            await db.execute(
                select(Transcript).where(Transcript.episode_id == ep_uuid)
            )
        ).scalar_one_or_none()
        segs, chunks = [], []
        if tr is not None:
            segs = (
                (
                    await db.execute(
                        select(TranscriptSegment)
                        .where(TranscriptSegment.transcript_id == tr.id)
                        .order_by(TranscriptSegment.start_time)
                    )
                )
                .scalars()
                .all()
            )
            chunks = (
                (
                    await db.execute(
                        select(TranscriptChunk).where(
                            TranscriptChunk.transcript_id == tr.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        queue_row = (
            await db.execute(
                select(TranscriptionQueue).where(
                    TranscriptionQueue.episode_id == ep_uuid
                )
            )
        ).scalar_one_or_none()
        return tr, segs, chunks, queue_row


# ─── Endpoint: auth ─────────────────────────────────────────────────────


async def test_unauthenticated_rejected(client, seeded_episode):
    r = await client.post(
        f"/admin/episodes/{seeded_episode['episode_id']}/transcript-import",
        json=_payload(),
    )
    assert r.status_code in (401, 403)


async def test_member_403(client, auth_member, seeded_episode):
    r = await client.post(
        f"/admin/episodes/{seeded_episode['episode_id']}/transcript-import",
        json=_payload(),
        cookies=auth_member["cookies"],
        headers=csrf_headers(auth_member["session_token"]),
    )
    assert r.status_code == 403


# ─── Endpoint: 202 happy path ───────────────────────────────────────────


async def test_valid_payload_returns_202_and_enqueues(
    client, auth_admin, seeded_episode
):
    with patch(
        "app.api.transcript_import.import_external_transcript.apply_async"
    ) as mock_apply:
        mock_apply.return_value.id = "fake-task-id"
        r = await client.post(
            f"/admin/episodes/{seeded_episode['episode_id']}/transcript-import",
            json=_payload(),
            cookies=auth_admin["cookies"],
            headers=csrf_headers(auth_admin["session_token"]),
        )
    assert r.status_code == 202
    body = r.json()
    assert body == {
        "task_id": "fake-task-id",
        "episode_id": seeded_episode["episode_id"],
    }
    mock_apply.assert_called_once()
    args = mock_apply.call_args.kwargs["args"]
    assert args[0] == seeded_episode["episode_id"]
    assert args[1]["segments"] == _payload()["segments"]
    assert mock_apply.call_args.kwargs["retry"] is False


# ─── Endpoint: 422 invalid payloads ────────────────────────────────────


@pytest.mark.parametrize(
    "bad_payload",
    [
        _payload(segments=[]),  # empty segments
        _payload(segments=[{"start": 5.0, "end": 3.0, "text": "倒退"}]),
        _payload(segments=[{"start": -1.0, "end": 3.0, "text": "負的"}]),
        _payload(text="   "),  # empty text
        _payload(segments=[{"start": 0.0, "end": 3.0, "text": " "}]),
    ],
    ids=[
        "empty-segments",
        "start-gt-end",
        "negative-start",
        "empty-text",
        "empty-segment-text",
    ],
)
async def test_invalid_payload_422_and_not_enqueued(
    client, auth_admin, seeded_episode, bad_payload
):
    with patch(
        "app.api.transcript_import.import_external_transcript.apply_async"
    ) as mock_apply:
        r = await client.post(
            f"/admin/episodes/{seeded_episode['episode_id']}/transcript-import",
            json=bad_payload,
            cookies=auth_admin["cookies"],
            headers=csrf_headers(auth_admin["session_token"]),
        )
    assert r.status_code == 422
    mock_apply.assert_not_called()


# ─── Endpoint: 404 / 409 ───────────────────────────────────────────────


async def test_unknown_episode_404(client, auth_admin):
    r = await client.post(
        f"/admin/episodes/{uuid.uuid4()}/transcript-import",
        json=_payload(),
        cookies=auth_admin["cookies"],
        headers=csrf_headers(auth_admin["session_token"]),
    )
    assert r.status_code == 404


@pytest.mark.parametrize("blocking_status", ["pending", "running"])
async def test_inflight_asr_blocks_import_409(
    client, auth_admin, seeded_episode, blocking_status
):
    from app.models.transcription_queue import QueueStatus, TranscriptionQueue

    async with AsyncSessionFactory() as db:
        db.add(
            TranscriptionQueue(
                episode_id=seeded_episode["ep_uuid"],
                show_id=seeded_episode["show_id"],
                status=QueueStatus(blocking_status),
                position=999999,
                whisper_model="large-v3",
            )
        )
        await db.commit()

    with patch(
        "app.api.transcript_import.import_external_transcript.apply_async"
    ) as mock_apply:
        r = await client.post(
            f"/admin/episodes/{seeded_episode['episode_id']}/transcript-import",
            json=_payload(),
            cookies=auth_admin["cookies"],
            headers=csrf_headers(auth_admin["session_token"]),
        )
    assert r.status_code == 409
    mock_apply.assert_not_called()


# ─── Task: queue row provenance + downstream artifacts ─────────────────


async def test_import_creates_queue_row_and_full_artifacts(
    seeded_episode, monkeypatch
):
    from app.models.transcript import TranscriptStatus
    from app.models.transcription_queue import QueueStatus

    _patch_import_externals(monkeypatch)
    result, mock_summary, mock_topic = await _run_import_task(
        seeded_episode["episode_id"], _payload()
    )
    assert result["status"] == "completed"
    assert result["segments"] == 2

    tr, segs, chunks, queue_row = await _load_artifacts(
        seeded_episode["ep_uuid"]
    )
    assert tr is not None and tr.status == TranscriptStatus.completed
    assert tr.language == "zh"
    assert len(segs) == 2
    assert segs[0].text == "今天聊滅火器的歌，"
    assert chunks and all(c.embedding is not None for c in chunks)
    assert chunks and all(c.embedding_v2 is not None for c in chunks)
    # Provenance: row created by the import ends completed + external label.
    assert queue_row is not None
    assert queue_row.status == QueueStatus.completed
    assert queue_row.whisper_model == EXTERNAL_LABEL
    # Downstream chain fired exactly like the provider path.
    mock_summary.assert_called_once_with(seeded_episode["episode_id"])
    mock_topic.assert_called_once_with(seeded_episode["episode_id"])


async def test_import_applies_asr_correction_rules(
    seeded_episode, monkeypatch
):
    """Import path shares the provider path's correction behavior (spec:
    Single pipeline for both entry paths)."""
    from app.models.asr_correction_term import AsrCorrectionTerm

    async with AsyncSessionFactory() as db:
        db.add(
            AsrCorrectionTerm(
                wrong="咪有企",
                correct="滅火器",
                scope="show",
                show_id=seeded_episode["show_id"],
                enabled=True,
            )
        )
        await db.commit()

    _patch_import_externals(monkeypatch)
    payload = _payload(
        text="今天聊咪有企的歌",
        segments=[{"start": 0.0, "end": 3.0, "text": "今天聊咪有企的歌"}],
    )
    try:
        result, _, _ = await _run_import_task(
            seeded_episode["episode_id"], payload
        )
        assert result["status"] == "completed"
        tr, segs, chunks, _ = await _load_artifacts(seeded_episode["ep_uuid"])
        assert "滅火器" in tr.content and "咪有企" not in tr.content
        assert segs and all("咪有企" not in s.text for s in segs)
        assert chunks and any("滅火器" in c.text for c in chunks)
    finally:
        async with AsyncSessionFactory() as db:
            await db.execute(
                delete(AsrCorrectionTerm).where(
                    AsrCorrectionTerm.show_id == seeded_episode["show_id"]
                )
            )
            await db.commit()


async def test_import_skips_homophone_detection(seeded_episode, monkeypatch):
    """D6（2026-07-07）：匯入路徑跳過 EQ2b LLM 同音字偵測——成本大頭
    （gemini-3.5-flash，全量 73%）+ 批次灌爆候選字。ASR 字典校正（第二層）
    不受影響（由 test_import_applies_asr_correction_rules 保證）。ASR 路徑
    維持 skip_homophone=False，行為不變。"""
    from app.workers import tasks

    _patch_import_externals(monkeypatch)
    # detect_homophones 被 spy 換掉：匯入路徑若誤呼叫，assert_not_called 會失敗。
    homophone_spy = AsyncMock(return_value=[])
    monkeypatch.setattr(
        tasks.asr_homophone, "detect_homophones", homophone_spy
    )

    result, _, _ = await _run_import_task(
        seeded_episode["episode_id"], _payload()
    )
    assert result["status"] == "completed"
    homophone_spy.assert_not_called()


async def test_import_revives_failed_queue_row(seeded_episode, monkeypatch):
    from app.models.transcription_queue import QueueStatus, TranscriptionQueue

    async with AsyncSessionFactory() as db:
        row = TranscriptionQueue(
            episode_id=seeded_episode["ep_uuid"],
            show_id=seeded_episode["show_id"],
            status=QueueStatus.failed,
            position=999999,
            whisper_model="large-v3",
            error_message="previous ASR failure",
        )
        db.add(row)
        await db.commit()
        original_row_id = row.id

    _patch_import_externals(monkeypatch)
    result, _, _ = await _run_import_task(
        seeded_episode["episode_id"], _payload()
    )
    assert result["status"] == "completed"

    _, _, _, queue_row = await _load_artifacts(seeded_episode["ep_uuid"])
    assert queue_row is not None
    assert queue_row.id == original_row_id  # revived, not recreated
    assert queue_row.status == QueueStatus.completed
    assert queue_row.whisper_model == EXTERNAL_LABEL
    assert queue_row.error_message is None


async def test_reimport_replaces_artifacts(seeded_episode, monkeypatch):
    _patch_import_externals(monkeypatch)
    result, _, _ = await _run_import_task(
        seeded_episode["episode_id"], _payload()
    )
    assert result["status"] == "completed"

    second = _payload(
        text="重匯之後的新內容。",
        segments=[{"start": 0.0, "end": 4.0, "text": "重匯之後的新內容。"}],
    )
    result, _, _ = await _run_import_task(seeded_episode["episode_id"], second)
    assert result["status"] == "completed"

    tr, segs, chunks, queue_row = await _load_artifacts(
        seeded_episode["ep_uuid"]
    )
    assert len(segs) == 1  # old segments deleted, rebuilt from new payload
    assert segs[0].text == "重匯之後的新內容。"
    assert tr.content == "重匯之後的新內容。"
    assert chunks and all("滅火器" not in c.text for c in chunks)
    assert queue_row.status.value == "completed"


async def test_embedding_failure_marks_transcript_failed(
    seeded_episode, monkeypatch
):
    from app.models.transcript import TranscriptStatus
    from app.models.transcription_queue import QueueStatus
    from app.workers import tasks

    _patch_import_externals(monkeypatch)

    def _boom(texts, cfg):
        raise RuntimeError("embedding API down")

    monkeypatch.setattr(tasks, "embed_texts_dual", _boom)

    result, mock_summary, _ = await _run_import_task(
        seeded_episode["episode_id"], _payload()
    )
    assert result["status"] == "failed"
    assert "embedding API down" in result["error"]

    tr, _, chunks, queue_row = await _load_artifacts(seeded_episode["ep_uuid"])
    assert tr is not None and tr.status == TranscriptStatus.failed
    assert "embedding API down" in tr.error_message
    assert chunks == []  # no partial chunks left behind
    assert queue_row is not None and queue_row.status == QueueStatus.failed
    mock_summary.assert_not_called()
