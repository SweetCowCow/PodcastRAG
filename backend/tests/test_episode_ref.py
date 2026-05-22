"""Tests for `episode_ref.extract_episode_ids_from_query` (retrieval-episode-
reference-handling change). Covers the 5 spec scenarios."""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.episode_ref import extract_episode_ids_from_query


def _mock_db_returning(rows_per_call: list[dict | None]) -> AsyncMock:
    """Build an AsyncSession mock whose `execute(...)` returns a chain that,
    on `.mappings().first()`, yields the next item from `rows_per_call`."""
    db = MagicMock()
    call_iter = iter(rows_per_call)

    async def fake_execute(*args, **kwargs):
        # Each .execute() call consumes one row from the queue.
        row = next(call_iter, None)
        result = MagicMock()
        mappings = MagicMock()
        mappings.first.return_value = row
        result.mappings.return_value = mappings
        return result

    db.execute = AsyncMock(side_effect=fake_execute)
    return db


@pytest.mark.asyncio
async def test_single_ep_reference_returns_one_uuid():
    show_id = uuid.uuid4()
    ep134_id = uuid.uuid4()
    db = _mock_db_returning([{"id": ep134_id}])
    result = await extract_episode_ids_from_query(
        db, show_id, "迪拉胖在 EP134 為什麼不挑振奮的開工歌"
    )
    assert result == [ep134_id]


@pytest.mark.asyncio
async def test_multi_ep_references_preserve_order_and_dedup():
    show_id = uuid.uuid4()
    ep134_id = uuid.uuid4()
    ep143_id = uuid.uuid4()
    db = _mock_db_returning([{"id": ep134_id}, {"id": ep143_id}])
    result = await extract_episode_ids_from_query(
        db, show_id, "比較 EP134 跟 EP143 跟 EP134 的差異"
    )
    # EP134 dedup → list[ep134, ep143]
    assert result == [ep134_id, ep143_id]
    # Only TWO db.execute calls (dedup'd before DB lookup)
    assert db.execute.call_count == 2


@pytest.mark.asyncio
async def test_no_ep_reference_returns_empty_list():
    show_id = uuid.uuid4()
    db = _mock_db_returning([])
    result = await extract_episode_ids_from_query(db, show_id, "歌單那幾集")
    assert result == []
    assert db.execute.call_count == 0  # no SQL when regex misses


@pytest.mark.asyncio
async def test_nonexistent_ep_returns_empty_and_logs_warning(caplog):
    show_id = uuid.uuid4()
    db = _mock_db_returning([None])  # DB returns no row
    with caplog.at_level(logging.WARNING, logger="app.services.episode_ref"):
        result = await extract_episode_ids_from_query(
            db, show_id, "EP999 講了什麼"
        )
    assert result == []
    assert any(
        "EP999" in rec.message and "not found" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_empty_and_whitespace_query():
    show_id = uuid.uuid4()
    db = _mock_db_returning([])
    assert await extract_episode_ids_from_query(db, show_id, "") == []
    assert db.execute.call_count == 0


@pytest.mark.asyncio
async def test_case_insensitive_and_whitespace_tolerant():
    show_id = uuid.uuid4()
    ep1_id = uuid.uuid4()
    db = _mock_db_returning([{"id": ep1_id}])
    result = await extract_episode_ids_from_query(
        db, show_id, "ep 1 講什麼"
    )
    assert result == [ep1_id]
