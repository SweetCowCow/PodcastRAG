"""Multi-turn EP-reference carry tests (change: multi-turn-epref-resolution-fix).

Covers three mechanical fixes in tools.py:
  1. find_episode_by_ref auto-pins resolved episode + envelope.auto_pinned bool
  2. search_within_episode / get_episode_summary / get_episode_segments
     fall back to ChatSessionState.focused_episode_id when episode_id arg is omitted
  3. pin_episode is idempotent (already_pinned flag) when target == current focus
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.chat_agent.state import ChatSessionState
from app.services.chat_agent.tools import (
    FindEpisodeByRefInput,
    GetEpisodeSegmentsInput,
    GetEpisodeSummaryInput,
    PinEpisodeInput,
    SearchWithinEpisodeInput,
    ToolContext,
    _find_episode_by_ref,
    _get_episode_segments,
    _get_episode_summary,
    _pin_episode,
    _search_within_episode,
)


EP143 = uuid.UUID("6c5ce32f-fb37-4aa0-b72c-7d14a7c1c163")
EP140 = uuid.UUID("11111111-1111-1111-1111-111111111111")
EP19 = uuid.UUID("88f78fbe-d216-4334-bf4f-e3e3caeea48d")
SHOW_ID = uuid.UUID("45fc2462-17cf-42f5-98a7-68fe1a222228")


def _ctx(state: ChatSessionState | None = None) -> ToolContext:
    return ToolContext(
        db=MagicMock(),
        show_id=SHOW_ID,
        state=state or ChatSessionState(session_id=uuid.uuid4()),
        state_store=MagicMock(),
    )


# ── 1.1 auto-pin on find_episode_by_ref ─────────────────────────────────

@pytest.mark.asyncio
async def test_find_episode_by_ref_auto_pins_on_resolve(monkeypatch):
    from app.services import episode_finders

    fake_ep = MagicMock()
    fake_ep.episode_id = EP143
    fake_ep.model_dump = MagicMock(return_value={"episode_id": str(EP143), "title": "EP143"})
    monkeypatch.setattr(episode_finders, "find_by_ref", AsyncMock(return_value=fake_ep))

    ctx = _ctx()
    assert ctx.state.focused_episode_id is None

    out = await _find_episode_by_ref(FindEpisodeByRefInput(ref="EP143"), ctx)

    assert out["auto_pinned"] is True
    assert out["episode"]["episode_id"] == str(EP143)
    assert ctx.state.focused_episode_id == EP143
    assert ctx.state.focused_episode_at is not None
    ctx.state_store.save.assert_called_once_with(ctx.state)


@pytest.mark.asyncio
async def test_find_episode_by_ref_failed_resolution_does_not_modify_state(monkeypatch):
    from app.services import episode_finders

    monkeypatch.setattr(episode_finders, "find_by_ref", AsyncMock(return_value=None))

    prior_at = datetime.now(timezone.utc)
    state = ChatSessionState(
        session_id=uuid.uuid4(),
        focused_episode_id=EP140,
        focused_episode_at=prior_at,
    )
    ctx = _ctx(state)

    out = await _find_episode_by_ref(FindEpisodeByRefInput(ref="EP9999"), ctx)

    assert out["auto_pinned"] is False
    assert out["episode"] is None
    assert ctx.state.focused_episode_id == EP140
    assert ctx.state.focused_episode_at == prior_at
    ctx.state_store.save.assert_not_called()


# ── 1.2 episode_id fallback ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_episode_id_fallback_explicit_preserved(monkeypatch):
    """Explicit episode_id wins even when session has a different focused episode."""
    state = ChatSessionState(
        session_id=uuid.uuid4(),
        focused_episode_id=EP143,
        focused_episode_at=datetime.now(timezone.utc),
    )
    ctx = _ctx(state)

    # Mock the DB call paths used by _get_episode_summary
    captured: dict[str, uuid.UUID] = {}

    async def fake_execute(stmt, params):
        captured["episode_id"] = params["episode_id"]
        row = {"ai_summary": "S", "title": "EP140-title"}
        mock = MagicMock()
        mock.mappings = MagicMock(return_value=MagicMock(first=MagicMock(return_value=row)))
        return mock

    ctx.db.execute = AsyncMock(side_effect=fake_execute)

    out = await _get_episode_summary(GetEpisodeSummaryInput(episode_id=EP140), ctx)

    assert captured["episode_id"] == EP140  # explicit, not the session-focused EP143
    assert out["episode_id_source"] == "explicit"
    assert "effective_episode_id" not in out
    assert out["title"] == "EP140-title"


@pytest.mark.asyncio
async def test_episode_id_fallback_session_focused(monkeypatch):
    """Omitted episode_id falls back to session focused_episode_id."""
    state = ChatSessionState(
        session_id=uuid.uuid4(),
        focused_episode_id=EP143,
        focused_episode_at=datetime.now(timezone.utc),
    )
    ctx = _ctx(state)

    captured: dict[str, uuid.UUID] = {}

    async def fake_execute(stmt, params):
        captured["episode_id"] = params["episode_id"]
        row = {"ai_summary": "S", "title": "EP143-title"}
        mock = MagicMock()
        mock.mappings = MagicMock(return_value=MagicMock(first=MagicMock(return_value=row)))
        return mock

    ctx.db.execute = AsyncMock(side_effect=fake_execute)

    out = await _get_episode_summary(GetEpisodeSummaryInput(), ctx)

    assert captured["episode_id"] == EP143  # substituted from session
    assert out["episode_id_source"] == "session_focused"
    assert out["effective_episode_id"] == str(EP143)
    assert out["episode_id"] == str(EP143)


@pytest.mark.asyncio
async def test_episode_id_fallback_missing_returns_guided_error(monkeypatch):
    """Both omitted args and no session focus → guided error envelope, no DB call."""
    state = ChatSessionState(session_id=uuid.uuid4())  # no focused_episode_id
    ctx = _ctx(state)
    ctx.db.execute = AsyncMock(side_effect=AssertionError("DB MUST NOT be invoked"))

    out = await _get_episode_segments(GetEpisodeSegmentsInput(), ctx)

    assert out["episode_id_source"] == "missing"
    assert "find_episode_by_ref" in out["user_hint"]
    assert "error" in out
    ctx.db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_search_within_episode_fallback_to_session_focused(monkeypatch):
    """search_within_episode also honours session fallback (not just summary/segments)."""
    from app.services.chat_agent import tools as tools_mod

    state = ChatSessionState(
        session_id=uuid.uuid4(),
        focused_episode_id=EP19,
        focused_episode_at=datetime.now(timezone.utc),
    )
    ctx = _ctx(state)

    monkeypatch.setattr(tools_mod, "_embed_query", AsyncMock(return_value=[0.0] * 8))
    captured: dict = {}

    async def fake_retrieve(db, *, show_id, query_embedding, question, k, episode_id_filter=None):
        captured["episode_id_filter"] = episode_id_filter
        return []

    monkeypatch.setattr(tools_mod.rag, "retrieve_hybrid", fake_retrieve)

    out = await _search_within_episode(SearchWithinEpisodeInput(query="動漫歌單"), ctx)

    assert captured["episode_id_filter"] == [EP19]
    assert out["episode_id_source"] == "session_focused"
    assert out["effective_episode_id"] == str(EP19)


# ── 1.3 pin_episode idempotent ──────────────────────────────────────────

def test_pin_episode_idempotent_already_pinned():
    state = ChatSessionState(
        session_id=uuid.uuid4(),
        focused_episode_id=EP143,
        focused_episode_at=datetime.now(timezone.utc),
    )
    ctx = _ctx(state)

    out = _pin_episode(PinEpisodeInput(episode_id=EP143), ctx)

    assert out["ok"] is True
    assert out["already_pinned"] is True
    assert out["focused_episode_id"] == str(EP143)
    assert ctx.state.focused_episode_id == EP143  # unchanged


def test_pin_episode_to_different_episode_normal_write():
    state = ChatSessionState(
        session_id=uuid.uuid4(),
        focused_episode_id=EP143,
        focused_episode_at=datetime.now(timezone.utc),
    )
    ctx = _ctx(state)

    out = _pin_episode(PinEpisodeInput(episode_id=EP140), ctx)

    assert out["ok"] is True
    assert out["already_pinned"] is False
    assert ctx.state.focused_episode_id == EP140


def test_pin_episode_from_empty_state_normal_write():
    state = ChatSessionState(session_id=uuid.uuid4())  # no focus
    ctx = _ctx(state)

    out = _pin_episode(PinEpisodeInput(episode_id=EP19), ctx)

    assert out["ok"] is True
    assert out["already_pinned"] is False
    assert ctx.state.focused_episode_id == EP19
