"""Integration test: post-success R2 audio cleanup in _run.

After a successful transcription the episode's R2 audio object is deleted and
`audio_storage_key` reset to NULL (playback uses the RSS audio_url; downstream
tasks read transcript text only). Cleanup is fail-open: a delete failure must
not affect the completed transcription, and must leave the key intact so a
later sweep can retry.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from tests.conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no local Postgres"
)


def _fake_result():
    text = "測試音檔清理"
    seg = SimpleNamespace(start=0.0, end=3.0, text=text)
    return SimpleNamespace(segments=[seg], text=text, language="zh")


def _fake_cfg(step_key: str):
    from app.services.ai_step_resolver import StepConfig

    return StepConfig(
        step_key=step_key,
        step_type=step_key,
        base_url="https://x",
        api_key="sk-fake",
        model="fake-model",
        extra_config={"prompt": "p"},
    )


@pytest_asyncio.fixture
async def seeded_episode(db_session):
    from app.models.episode import Episode
    from app.models.show import Show

    suffix = uuid.uuid4().hex[:6]
    show = Show(
        title=f"pytest-audioclean-{suffix}",
        rss_url=f"https://e.com/{suffix}.rss",
        language="zh",
    )
    db_session.add(show)
    await db_session.commit()
    await db_session.refresh(show)

    ep = Episode(
        show_id=show.id,
        guid=f"pytest-audioclean-{suffix}-ep",
        title=f"pytest-audioclean-{suffix} EP1",
        audio_url=f"https://e.com/{suffix}.mp3",
        audio_storage_key=f"audio/{suffix}.mp3",
    )
    db_session.add(ep)
    await db_session.commit()
    await db_session.refresh(ep)

    # teardown 用純值：測試中會 expire_all()，過期 ORM 物件的屬性存取
    # 在 async session 下會炸 MissingGreenlet。
    ep_id = ep.id
    show_id = show.id

    yield {
        "episode_id": str(ep_id),
        "ep_uuid": ep_id,
        "storage_key": f"audio/{suffix}.mp3",
    }

    from app.models.transcript import Transcript
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment

    tr = (
        await db_session.execute(
            select(Transcript).where(Transcript.episode_id == ep_id)
        )
    ).scalar_one_or_none()
    if tr is not None:
        tr_id = tr.id
        await db_session.execute(
            delete(TranscriptChunk).where(TranscriptChunk.transcript_id == tr_id)
        )
        await db_session.execute(
            delete(TranscriptSegment).where(
                TranscriptSegment.transcript_id == tr_id
            )
        )
        await db_session.execute(delete(Transcript).where(Transcript.id == tr_id))
    await db_session.execute(delete(Episode).where(Episode.id == ep_id))
    await db_session.execute(delete(Show).where(Show.id == show_id))
    await db_session.commit()


def _patch_run_externals(monkeypatch):
    from app.workers import tasks

    fake_provider = SimpleNamespace(
        transcribe=AsyncMock(return_value=_fake_result())
    )
    monkeypatch.setattr(tasks, "_is_queue_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(tasks, "_mark_queue_finished", AsyncMock())
    monkeypatch.setattr(tasks.storage, "download_to_temp", lambda key: "/tmp/fake.mp3")
    monkeypatch.setattr(
        tasks, "get_step_config", AsyncMock(side_effect=lambda s, k: _fake_cfg(k))
    )
    monkeypatch.setattr(tasks, "get_provider", lambda cfg: fake_provider)
    monkeypatch.setattr(
        tasks,
        "embed_texts_dual",
        lambda texts, cfg: (
            [[0.1] * 1536 for _ in texts],
            [[0.2] * 3072 for _ in texts],
        ),
    )
    monkeypatch.setattr(tasks.tokenizer, "load_dictionary", AsyncMock(return_value=0))
    monkeypatch.setattr(tasks.tokenizer, "tokenize", lambda t: list(t))
    monkeypatch.setattr(
        tasks.asr_homophone,
        "get_step_config",
        AsyncMock(side_effect=lambda s, k: _fake_cfg(k)),
    )
    monkeypatch.setattr(
        tasks.asr_homophone, "_call_llm", lambda client, **kw: "[]"
    )


async def _load_key(db_session, ep_uuid):
    from app.models.episode import Episode

    # _run 用自己的 engine/session 寫入：先結束舊 txn 並清 identity map
    # 快取，否則 select 回傳 fixture 留下的舊物件、看不到新值。
    await db_session.commit()
    db_session.expire_all()
    ep = (
        await db_session.execute(select(Episode).where(Episode.id == ep_uuid))
    ).scalar_one()
    return ep.audio_storage_key


async def test_success_deletes_audio_and_clears_key(
    db_session, seeded_episode, monkeypatch
):
    from app.workers import tasks

    _patch_run_externals(monkeypatch)
    deleted_keys = []
    monkeypatch.setattr(
        tasks.storage, "delete_object", lambda key: deleted_keys.append(key)
    )

    result = await tasks._run(seeded_episode["episode_id"])
    assert result["status"] == "completed"

    assert deleted_keys == [seeded_episode["storage_key"]]
    assert await _load_key(db_session, seeded_episode["ep_uuid"]) is None


async def test_cleanup_fail_open_keeps_key_and_completion(
    db_session, seeded_episode, monkeypatch
):
    from app.services.storage import StorageError
    from app.workers import tasks

    _patch_run_externals(monkeypatch)

    def _boom(key):
        raise StorageError(f"simulated delete failure ({key})")

    monkeypatch.setattr(tasks.storage, "delete_object", _boom)

    result = await tasks._run(seeded_episode["episode_id"])
    assert result["status"] == "completed"

    # delete 失敗時 key 必須保留，之後仍能定位到殘留物件重清
    assert (
        await _load_key(db_session, seeded_episode["ep_uuid"])
        == seeded_episode["storage_key"]
    )
