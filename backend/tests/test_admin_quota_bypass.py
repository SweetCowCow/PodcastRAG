"""Test admin role bypasses _atomic_decrement_quota.

Spec: user-quota / Requirement: Query endpoint atomically decrements quota
- admin path: skip _atomic_decrement_quota, still UPDATE total_queries+1, return quota_remaining=-1
- non-admin path: existing _atomic_decrement_quota behavior unchanged
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.query import query_show
from app.schemas.query import QueryRequest, ChatResponse


def _fake_step_config(model: str = "gpt-4o") -> MagicMock:
    cfg = MagicMock()
    cfg.base_url = "https://fake.endpoint/v1"
    cfg.api_key = "sk-fake"
    cfg.model = model
    return cfg


def _make_user(role: str) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = role
    return u


def _make_show() -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    return s


def _make_db(show: MagicMock) -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock(return_value=show)
    return db


def _fake_agent_result(answer: str = "stub answer") -> MagicMock:
    r = MagicMock()
    r.answer = answer
    r.tool_calls = []
    r.agent_truncated = False
    return r


@pytest.mark.asyncio
async def test_admin_role_bypasses_atomic_decrement_quota():
    """Admin user: _atomic_decrement_quota MUST NOT be called; response carries -1."""
    show_id = uuid.uuid4()
    user = _make_user(role="admin")
    show = _make_show()
    show.id = show_id
    db = _make_db(show)

    with (
        patch("app.api.query._atomic_decrement_quota", new_callable=AsyncMock) as mock_atomic,
        patch("app.api.query.settings") as mock_settings,
        patch("app.api.query.run_agent", new_callable=AsyncMock, return_value=_fake_agent_result()),
    ):
        mock_settings.enable_agentic_chat = True
        payload = QueryRequest(mode="chat", question="test", session_id=uuid.uuid4())
        response = await query_show(show_id, payload, db, user, lang=None)

    mock_atomic.assert_not_called()
    # db.execute SHALL have been called for the admin total_queries UPDATE
    assert db.execute.await_count >= 1, "admin path SHALL run UPDATE total_queries"
    assert db.commit.await_count >= 1, "admin path SHALL commit"
    assert isinstance(response, ChatResponse)
    assert response.quota_remaining == -1


@pytest.mark.asyncio
async def test_admin_bypass_works_when_quota_remaining_would_be_zero():
    """Admin path SHALL NOT raise 429 even when DB quota_remaining is 0 — bypass branch
    never inspects the value. Mock _atomic_decrement_quota to raise to prove it isn't called.
    """
    show_id = uuid.uuid4()
    user = _make_user(role="admin")
    show = _make_show()
    show.id = show_id
    db = _make_db(show)

    from fastapi import HTTPException

    async def _exploding_atomic(*args, **kwargs):
        raise HTTPException(status_code=429, detail="should not be reached")

    with (
        patch("app.api.query._atomic_decrement_quota", side_effect=_exploding_atomic),
        patch("app.api.query.settings") as mock_settings,
        patch("app.api.query.run_agent", new_callable=AsyncMock, return_value=_fake_agent_result()),
    ):
        mock_settings.enable_agentic_chat = True
        payload = QueryRequest(mode="chat", question="test", session_id=uuid.uuid4())
        response = await query_show(show_id, payload, db, user, lang=None)

    assert isinstance(response, ChatResponse)
    assert response.quota_remaining == -1


@pytest.mark.asyncio
async def test_member_role_still_decrements_quota():
    """Non-admin (role=member) path SHALL still go through _atomic_decrement_quota."""
    show_id = uuid.uuid4()
    user = _make_user(role="member")
    show = _make_show()
    show.id = show_id
    db = _make_db(show)
    QUOTA_AFTER = 9

    with (
        patch("app.api.query._atomic_decrement_quota", new_callable=AsyncMock, return_value=QUOTA_AFTER) as mock_atomic,
        patch("app.api.query.settings") as mock_settings,
        patch("app.api.query.run_agent", new_callable=AsyncMock, return_value=_fake_agent_result()),
    ):
        mock_settings.enable_agentic_chat = True
        payload = QueryRequest(mode="chat", question="test", session_id=uuid.uuid4())
        response = await query_show(show_id, payload, db, user, lang=None)

    mock_atomic.assert_awaited_once_with(db, user.id)
    assert isinstance(response, ChatResponse)
    assert response.quota_remaining == QUOTA_AFTER


@pytest.mark.asyncio
async def test_member_with_zero_quota_still_returns_429():
    """Non-admin user with quota=0 SHALL get 429 — _atomic_decrement_quota raises and propagates."""
    show_id = uuid.uuid4()
    user = _make_user(role="member")
    show = _make_show()
    show.id = show_id
    db = _make_db(show)

    from fastapi import HTTPException

    async def _quota_exhausted(*args, **kwargs):
        raise HTTPException(status_code=429, detail={"error_code": "quota_exhausted"})

    with (
        patch("app.api.query._atomic_decrement_quota", side_effect=_quota_exhausted),
        patch("app.api.query.settings") as mock_settings,
    ):
        mock_settings.enable_agentic_chat = True
        payload = QueryRequest(mode="chat", question="test", session_id=uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await query_show(show_id, payload, db, user, lang=None)

    assert exc_info.value.status_code == 429
