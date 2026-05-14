"""Tests for app.services.query_entity.extract_entities — covers happy
paths + the three fail-open branches (API error / invalid JSON /
schema mismatch).

LLM client is mocked; no network calls.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import APIError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.query_entity import QueryEntities
from app.services.query_entity import ExtractionStatus, extract_entities


def _mock_client(content: str | None) -> AsyncMock:
    """Build an AsyncOpenAI-shaped mock that returns `content` from chat.completions.create()."""
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


@pytest.mark.asyncio
async def test_extract_entities_guest_only():
    payload = {"date_range": None, "guests": ["馬世芳"], "topics": []}
    client = _mock_client(json.dumps(payload))
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="馬世芳上過哪幾集？",
    )
    assert status == ExtractionStatus.ok
    assert entities.guests == ["馬世芳"]
    assert entities.date_range is None
    assert entities.topics == []


@pytest.mark.asyncio
async def test_extract_entities_date_range():
    payload = {
        "date_range": ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"],
        "guests": [],
        "topics": [],
    }
    client = _mock_client(json.dumps(payload))
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="2024 那集是哪集？",
    )
    assert status == ExtractionStatus.ok
    assert entities.date_range is not None
    start, end = entities.date_range
    assert start.year == 2024 and end.year == 2025


@pytest.mark.asyncio
async def test_extract_entities_topic_only():
    payload = {"date_range": None, "guests": [], "topics": ["歌單"]}
    client = _mock_client(json.dumps(payload))
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="節目裡有哪些集是歌單？",
    )
    assert status == ExtractionStatus.ok
    assert entities.topics == ["歌單"]


@pytest.mark.asyncio
async def test_extract_entities_multi_topic_and_guest():
    payload = {
        "date_range": None,
        "guests": ["楊大正"],
        "topics": ["高雄美食", "鴨肉"],
    }
    client = _mock_client(json.dumps(payload))
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="高雄美食那幾集楊大正有講到鴨肉嗎？",
    )
    assert status == ExtractionStatus.ok
    assert entities.guests == ["楊大正"]
    assert "高雄美食" in entities.topics and "鴨肉" in entities.topics


@pytest.mark.asyncio
async def test_extract_entities_empty_all():
    payload = {"date_range": None, "guests": [], "topics": []}
    client = _mock_client(json.dumps(payload))
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="你們是誰？",
    )
    assert status == ExtractionStatus.ok
    assert entities.is_empty()


@pytest.mark.asyncio
async def test_extract_entities_fails_open_on_api_error():
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=APIError("upstream-down", request=MagicMock(), body=None)
    )
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="anything",
    )
    assert status == ExtractionStatus.api_error
    assert entities.is_empty()


@pytest.mark.asyncio
async def test_extract_entities_fails_open_on_invalid_json():
    client = _mock_client("this is not json")
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="anything",
    )
    assert status == ExtractionStatus.invalid_json
    assert entities.is_empty()


@pytest.mark.asyncio
async def test_extract_entities_fails_open_on_schema_mismatch():
    # `guests` should be list[str], not str
    payload = {"date_range": None, "guests": "馬世芳", "topics": []}
    client = _mock_client(json.dumps(payload))
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="馬世芳上過哪幾集？",
    )
    assert status == ExtractionStatus.schema_mismatch
    assert entities.is_empty()


@pytest.mark.asyncio
async def test_extract_entities_fails_open_on_empty_content():
    client = _mock_client("")
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="anything",
    )
    assert status == ExtractionStatus.empty_response
    assert entities.is_empty()


@pytest.mark.asyncio
async def test_extract_entities_passes_now_to_prompt():
    # Smoke: caller can inject `now` for deterministic tests
    payload = {"date_range": None, "guests": [], "topics": []}
    client = _mock_client(json.dumps(payload))
    fixed_now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    entities, status = await extract_entities(
        client, model="gpt-4o-mini", question="anything", now=fixed_now,
    )
    assert status == ExtractionStatus.ok
    # Verify our injected datetime made it into the user message
    call = client.chat.completions.create.call_args
    user_msg = next(m for m in call.kwargs["messages"] if m["role"] == "user")
    assert "2026-05-14" in user_msg["content"]
