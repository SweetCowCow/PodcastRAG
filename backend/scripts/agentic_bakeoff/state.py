"""ChatSessionState (L1 memory) — Redis-backed, 2h TTL.

`focused_episode_id` auto-expires after 10 min idle (design D-L0/L1).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import redis
from pydantic import BaseModel, Field


SESSION_TTL_SEC = 7200  # 2h
FOCUSED_EPISODE_IDLE_SEC = 600  # 10 min


class ChatSessionState(BaseModel):
    session_id: str
    show_id: uuid.UUID
    focused_episode_id: uuid.UUID | None = None
    focused_episode_pinned_at: datetime | None = None
    last_enumeration_episodes: list[uuid.UUID] = Field(default_factory=list)
    history_summary: str = ""

    def focused_is_fresh(self, now: datetime | None = None) -> bool:
        if self.focused_episode_id is None or self.focused_episode_pinned_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - self.focused_episode_pinned_at) <= timedelta(
            seconds=FOCUSED_EPISODE_IDLE_SEC
        )

    @classmethod
    def key(cls, session_id: str) -> str:
        return f"agentic_bakeoff:session:{session_id}"


def load_state(
    rc: redis.Redis, session_id: str, show_id: uuid.UUID
) -> ChatSessionState:
    raw = rc.get(ChatSessionState.key(session_id))
    if raw:
        data = json.loads(raw)
        return ChatSessionState.model_validate(data)
    return ChatSessionState(session_id=session_id, show_id=show_id)


def save_state(rc: redis.Redis, state: ChatSessionState) -> None:
    rc.setex(
        ChatSessionState.key(state.session_id),
        SESSION_TTL_SEC,
        state.model_dump_json(),
    )


def clear_state(rc: redis.Redis, session_id: str) -> None:
    rc.delete(ChatSessionState.key(session_id))
