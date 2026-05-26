"""Tests for app.services.rag_rerank (change: retrieval-cross-episode-chunk-recovery task 2.x)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.rag_rerank import llm_rerank


def _chunks(n: int) -> list[dict]:
    return [
        {"chunk_id": f"c{i}", "text": f"chunk {i} content", "episode_id": "ep1"}
        for i in range(1, n + 1)
    ]


def _llm_resp(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


@pytest.mark.asyncio
async def test_rerank_happy_path():
    """Mock LLM returns valid JSON reorder; verify output order matches."""
    chunks = _chunks(10)
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_llm_resp('{"ranked_chunk_ids": ["c5","c1","c8","c2","c3"]}')
    )

    out, applied = await llm_rerank("Q", chunks, k=3, client=client)

    assert applied is True
    assert [c["chunk_id"] for c in out] == ["c5", "c1", "c8"]


@pytest.mark.asyncio
async def test_rerank_timeout_fallback():
    """Mock LLM hangs past timeout; verify fallback to RRF top-k."""
    chunks = _chunks(10)
    client = AsyncMock()

    async def _slow(*a, **kw):
        await asyncio.sleep(5)
        return _llm_resp("{}")

    client.chat.completions.create = _slow

    out, applied = await llm_rerank("Q", chunks, k=3, client=client, timeout_s=0.1)

    assert applied is False
    assert [c["chunk_id"] for c in out] == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_rerank_malformed_json_fallback():
    """Mock LLM returns garbage text; verify fallback to RRF top-k."""
    chunks = _chunks(10)
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_llm_resp("not json at all")
    )

    out, applied = await llm_rerank("Q", chunks, k=3, client=client)

    assert applied is False
    assert [c["chunk_id"] for c in out] == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_rerank_unknown_chunk_ids_dropped():
    """LLM returns some unknown chunk_ids; verify they're dropped, known kept."""
    chunks = _chunks(10)
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_llm_resp(
            '{"ranked_chunk_ids": ["c5","UNKNOWN_A","c1","UNKNOWN_B","c8"]}'
        )
    )

    out, applied = await llm_rerank("Q", chunks, k=3, client=client)

    assert applied is True
    out_ids = [c["chunk_id"] for c in out]
    assert "UNKNOWN_A" not in out_ids
    assert "UNKNOWN_B" not in out_ids
    assert out_ids[:3] == ["c5", "c1", "c8"]


@pytest.mark.asyncio
async def test_rerank_backfill_when_short():
    """LLM only returns 2 valid IDs (k=5); verify gap filled from RRF order."""
    chunks = _chunks(10)
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_llm_resp('{"ranked_chunk_ids": ["c7","c3"]}')
    )

    out, applied = await llm_rerank("Q", chunks, k=5, client=client)

    assert applied is True
    out_ids = [c["chunk_id"] for c in out]
    # First two = LLM's ranking; next 3 = first 3 from input that aren't already in
    assert out_ids[:2] == ["c7", "c3"]
    # Backfill takes original chunk order, skipping c7 and c3
    assert out_ids[2:] == ["c1", "c2", "c4"]
