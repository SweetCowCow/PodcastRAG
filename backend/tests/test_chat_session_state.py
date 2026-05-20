"""Unit tests for `chat_agent.state` (chat-agentic-tool-routing change).

`fakeredis` is intentionally not used — backend already has its own
`_FakeRedis` pattern in `test_admin_processing_stats_api.py`, so we sustain
the same convention to keep dependency surface minimal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.chat_agent.state import (
    ChatSessionState,
    ChatSessionStateStore,
    _redis_key,
)


class _FakeRedis:
    """In-memory stand-in for `redis.Redis` supporting get/set(ex=...)/delete + TTL inspection."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self._ttl: dict[str, int] = {}

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value, ex: int | None = None) -> None:
        if isinstance(value, str):
            value = value.encode()
        self._store[key] = value
        if ex is not None:
            self._ttl[key] = ex

    def delete(self, key: str) -> int:
        self._ttl.pop(key, None)
        return 1 if self._store.pop(key, None) is not None else 0

    def ttl(self, key: str) -> int:
        return self._ttl.get(key, -2)


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def store(fake_redis: _FakeRedis) -> ChatSessionStateStore:
    return ChatSessionStateStore(client=fake_redis)


def test_round_trip_save_load(store: ChatSessionStateStore) -> None:
    sid = uuid.uuid4()
    ep_id = uuid.uuid4()
    state = ChatSessionState(
        session_id=sid,
        focused_episode_id=ep_id,
        focused_episode_at=datetime.now(timezone.utc),
        history_summary="some prior summary",
    )
    store.save(state)
    loaded = store.load(sid)
    assert loaded is not None
    assert loaded.session_id == sid
    assert loaded.focused_episode_id == ep_id
    assert loaded.history_summary == "some prior summary"


def test_missing_session_returns_none_no_autocreate(
    store: ChatSessionStateStore, fake_redis: _FakeRedis
) -> None:
    sid = uuid.uuid4()
    assert store.load(sid) is None
    assert _redis_key(sid) not in fake_redis._store  # no auto-create


def test_ttl_refresh_on_write(
    store: ChatSessionStateStore, fake_redis: _FakeRedis
) -> None:
    sid = uuid.uuid4()
    state = ChatSessionState(session_id=sid)
    store.save(state)
    first_ttl = fake_redis.ttl(_redis_key(sid))
    assert first_ttl == 7200  # agentic_chat_l1_ttl_seconds default

    # Mutate-and-save again with a stale TTL artefact to prove refresh
    fake_redis._ttl[_redis_key(sid)] = 1
    state.history_summary = "updated"
    store.save(state)
    refreshed_ttl = fake_redis.ttl(_redis_key(sid))
    assert refreshed_ttl == 7200


def test_lazy_expire_focused_episode_after_11min(
    store: ChatSessionStateStore, fake_redis: _FakeRedis
) -> None:
    sid = uuid.uuid4()
    eleven_min_ago = datetime.now(timezone.utc) - timedelta(minutes=11)
    state = ChatSessionState(
        session_id=sid,
        focused_episode_id=uuid.uuid4(),
        focused_episode_at=eleven_min_ago,
    )
    # Persist directly via fake_redis to bypass save() refreshing updated_at
    fake_redis.set(_redis_key(sid), state.model_dump_json(), ex=7200)

    loaded = store.load(sid)
    assert loaded is not None
    assert loaded.focused_episode_id is None
    assert loaded.focused_episode_at is None
    # And lazy expiry MUST NOT write back
    raw_after = fake_redis.get(_redis_key(sid))
    raw_state = ChatSessionState.model_validate_json(raw_after)
    assert raw_state.focused_episode_id is not None  # still set on disk


def test_lazy_expire_last_enumeration_after_11min(
    store: ChatSessionStateStore, fake_redis: _FakeRedis
) -> None:
    sid = uuid.uuid4()
    eleven_min_ago = datetime.now(timezone.utc) - timedelta(minutes=11)
    state = ChatSessionState(
        session_id=sid,
        last_enumeration_episodes=[uuid.uuid4(), uuid.uuid4()],
        last_enumeration_at=eleven_min_ago,
    )
    fake_redis.set(_redis_key(sid), state.model_dump_json(), ex=7200)

    loaded = store.load(sid)
    assert loaded is not None
    assert loaded.last_enumeration_episodes == []
    assert loaded.last_enumeration_at is None


def test_enumeration_fifo_truncation_at_20() -> None:
    sid = uuid.uuid4()
    # Scenario from spec: 18 existing + 5 new → exactly 20 retained, 3 oldest dropped.
    eps = [uuid.uuid4() for _ in range(23)]
    state = ChatSessionState(session_id=sid, last_enumeration_episodes=eps)
    assert len(state.last_enumeration_episodes) == 20
    assert state.last_enumeration_episodes == eps[-20:]  # FIFO drops oldest 3
