"""Tests for app.services.rag_rerank.voyage_rerank (change: retrieval-rerank-via-voyage task 2.x)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.rag_rerank import voyage_rerank


def _chunks(n: int) -> list[dict]:
    return [
        {"chunk_id": f"c{i}", "text": f"chunk {i} content", "episode_id": "ep1"}
        for i in range(1, n + 1)
    ]


def _voyage_resp(indices: list[int]):
    """Mock voyageai response: results sorted by relevance with given indices."""
    return SimpleNamespace(
        results=[
            SimpleNamespace(index=i, relevance_score=1.0 - 0.1 * pos, document=f"doc_{i}")
            for pos, i in enumerate(indices)
        ],
        total_tokens=100,
    )


@pytest.mark.asyncio
async def test_voyage_happy_path():
    """Mock Voyage returns reorder by index; verify output picks chunks in that order."""
    chunks = _chunks(10)
    client = AsyncMock()
    # Voyage returned indices 4, 0, 7, 1, 2 → chunks c5, c1, c8, c2, c3
    client.rerank = AsyncMock(return_value=_voyage_resp([4, 0, 7, 1, 2]))

    out, applied = await voyage_rerank("Q", chunks, k=3, client=client)

    assert applied is True
    assert [c["chunk_id"] for c in out] == ["c5", "c1", "c8"]


@pytest.mark.asyncio
async def test_voyage_timeout_fallback():
    """Mock Voyage hangs past timeout; verify fallback to RRF top-k."""
    chunks = _chunks(10)
    client = AsyncMock()

    async def _slow(**kw):
        await asyncio.sleep(5)
        return _voyage_resp([0])

    client.rerank = _slow

    out, applied = await voyage_rerank("Q", chunks, k=3, client=client, timeout_s=0.1)

    assert applied is False
    assert [c["chunk_id"] for c in out] == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_voyage_api_error_fallback():
    """Mock Voyage raises generic Exception; verify fallback to RRF top-k."""
    chunks = _chunks(10)
    client = AsyncMock()
    client.rerank = AsyncMock(side_effect=RuntimeError("voyage 5xx"))

    out, applied = await voyage_rerank("Q", chunks, k=3, client=client)

    assert applied is False
    assert [c["chunk_id"] for c in out] == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_voyage_unknown_index_dropped():
    """Voyage returns indices outside [0, n); verify they're dropped, valid ones kept."""
    chunks = _chunks(10)
    client = AsyncMock()
    # Indices include 99 (out of range) and -1 (negative) — both dropped
    client.rerank = AsyncMock(return_value=_voyage_resp([4, 99, 0, -1, 7]))

    out, applied = await voyage_rerank("Q", chunks, k=3, client=client)

    assert applied is True
    assert [c["chunk_id"] for c in out] == ["c5", "c1", "c8"]


@pytest.mark.asyncio
async def test_voyage_backfill_when_short():
    """Voyage only returns 2 valid indices (k=5); verify gap filled from input order."""
    chunks = _chunks(10)
    client = AsyncMock()
    # Voyage returns 2 valid + 1 unknown — only 2 valid → need 3 backfill
    client.rerank = AsyncMock(return_value=_voyage_resp([6, 2, 999]))

    out, applied = await voyage_rerank("Q", chunks, k=5, client=client)

    assert applied is True
    out_ids = [c["chunk_id"] for c in out]
    # First 2 from Voyage: c7, c3
    assert out_ids[:2] == ["c7", "c3"]
    # Backfill from input order, skipping c7 and c3
    assert out_ids[2:] == ["c1", "c2", "c4"]
