"""Test that quota decrement is uniform across agentic and rule-based paths.

Spec: Requirement: Quota accounting applies uniformly across both pipelines
- _atomic_decrement_quota is called at the query_show entry point, BEFORE
  the enable_agentic_chat flag check, so both paths always decrement once.
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


def _make_user() -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    return u


def _make_show() -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    return s


def _make_db(show: MagicMock) -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock(return_value=show)
    return db


@pytest.mark.asyncio
async def test_quota_decrement_uniform_across_pipelines():
    """Both the agentic path (flag=True) and rule-based path (flag=False)
    call _atomic_decrement_quota exactly once before serving the response.

    Verifies the contract: quota is decremented at the query_show entry,
    before any mode-specific branching, so neither path can skip it.
    """
    show_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user = _make_user()
    show = _make_show()
    show.id = show_id

    QUOTA_AFTER = 42

    fake_agent_result = MagicMock()
    fake_agent_result.answer = "Agentic answer"
    fake_agent_result.tool_calls = []
    fake_agent_result.agent_truncated = False

    # ── agentic path ──
    db_a = _make_db(show)
    with (
        patch("app.api.query._atomic_decrement_quota", new_callable=AsyncMock, return_value=QUOTA_AFTER) as mock_quota_a,
        patch("app.api.query.settings") as mock_settings_a,
        patch("app.api.query.run_agent", new_callable=AsyncMock, return_value=fake_agent_result),
    ):
        mock_settings_a.enable_agentic_chat = True
        payload_a = QueryRequest(mode="chat", question="test question", session_id=session_id)
        response_a = await query_show(show_id, payload_a, db_a, user, lang=None)

    mock_quota_a.assert_called_once_with(db_a, user.id)
    assert isinstance(response_a, ChatResponse)
    assert response_a.quota_remaining == QUOTA_AFTER

    # ── rule-based path ──
    db_b = _make_db(show)
    with (
        patch("app.api.query._atomic_decrement_quota", new_callable=AsyncMock, return_value=QUOTA_AFTER) as mock_quota_b,
        patch("app.api.query.settings") as mock_settings_b,
        patch("app.api.query.get_step_config", new_callable=AsyncMock, return_value=_fake_step_config()),
        patch("app.api.query.OpenAI"),  # stop OpenAI() from validating base_url
        patch("app.api.query.asyncio.to_thread", new_callable=AsyncMock, return_value=("答案", "答案", [])),
        patch("app.api.query._extract_entities_fail_open", new_callable=AsyncMock, return_value=MagicMock(guests=[], date_range=None, topic=None)),
        patch("app.api.query._entities_to_metadata_filters", return_value=MagicMock()),
        patch("app.api.query.rag._should_skip_routing", return_value=True),
        patch("app.api.query.rag.retrieve_hybrid", new_callable=AsyncMock, return_value=[]),
        patch("app.api.query.rag.enrich_hits", new_callable=AsyncMock),
        patch("app.api.query._compute_enumeration_episodes", new_callable=AsyncMock, return_value=(None, None)),
        patch("app.api.query.citation_parser.parse", return_value=("答案", [])),
    ):
        mock_settings_b.enable_agentic_chat = False
        payload_b = QueryRequest(mode="chat", question="test question")
        response_b = await query_show(show_id, payload_b, db_b, user, lang=None)

    mock_quota_b.assert_called_once_with(db_b, user.id)
    assert isinstance(response_b, ChatResponse)
    assert response_b.quota_remaining == QUOTA_AFTER
