"""ChatSessionState + Redis 持久層（chat-agentic-tool-routing change）。

L1 session-scoped 對話 anchor：focused episode、最近一次列舉結果、滾動
history summary。資料存 Redis（TTL 預設 2h），10 min idle 後讀時 lazy expire
focused / enumeration anchor（不 write back）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import redis
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


_ENUMERATION_CAP = 20

_REDIS_KEY_PREFIX = "chat:session:"


def _redis_key(session_id: UUID) -> str:
    return f"{_REDIS_KEY_PREFIX}{session_id}"


def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.celery_broker_url)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatSessionState(BaseModel):
    """Per-session conversational anchors stored in Redis under
    `chat:session:{session_id}` with TTL `agentic_chat_l1_ttl_seconds`.

    `last_enumeration_episodes` is FIFO-capped at 20 entries — when input
    exceeds the cap the OLDEST entries are dropped so the most recent
    enumeration result is always retained.
    """

    session_id: UUID
    focused_episode_id: UUID | None = None
    focused_episode_at: datetime | None = None
    last_enumeration_episodes: list[UUID] = Field(default_factory=list)
    last_enumeration_at: datetime | None = None
    history_summary: str = Field(default="", max_length=300)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("last_enumeration_episodes", mode="before")
    @classmethod
    def _truncate_enumeration_fifo(cls, v: Any) -> Any:
        if isinstance(v, list) and len(v) > _ENUMERATION_CAP:
            return v[-_ENUMERATION_CAP:]
        return v


class ChatSessionStateStore:
    """Redis-backed CRUD for `ChatSessionState`.

    - Key: `chat:session:{session_id}` (JSON string body).
    - TTL: `settings.agentic_chat_l1_ttl_seconds` (default 2h), refreshed
      on every save.
    - Reads return `None` for missing keys and SHALL NOT auto-create rows.
    - Loads apply lazy expiry to `focused_*` and `last_enumeration_*`
      anchors based on idle thresholds in settings (task 2.3).
    """

    def __init__(self, client: redis.Redis | None = None) -> None:
        self._client = client or _get_redis()

    def load(self, session_id: UUID) -> ChatSessionState | None:
        raw = self._client.get(_redis_key(session_id))
        if raw is None:
            return None
        state = ChatSessionState.model_validate_json(raw)
        self._apply_lazy_expiry(state)
        return state

    def save(self, state: ChatSessionState) -> None:
        state.updated_at = _utcnow()
        self._client.set(
            _redis_key(state.session_id),
            state.model_dump_json(),
            ex=settings.agentic_chat_l1_ttl_seconds,
        )

    def delete(self, session_id: UUID) -> None:
        self._client.delete(_redis_key(session_id))

    @staticmethod
    def _apply_lazy_expiry(state: ChatSessionState) -> None:
        """Mutate `state` in-place to drop expired focused / enumeration
        anchors. NOT written back to Redis — pure read-side expiry so a
        passive read never churns the key."""

        now = _utcnow()
        focused_idle = settings.agentic_chat_focused_idle_seconds
        if (
            state.focused_episode_at is not None
            and (now - state.focused_episode_at).total_seconds() > focused_idle
        ):
            state.focused_episode_id = None
            state.focused_episode_at = None

        enum_ttl = settings.agentic_chat_enumeration_ttl_seconds
        if (
            state.last_enumeration_at is not None
            and (now - state.last_enumeration_at).total_seconds() > enum_ttl
        ):
            state.last_enumeration_episodes = []
            state.last_enumeration_at = None
