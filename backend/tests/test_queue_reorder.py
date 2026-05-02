"""Tests for PATCH /admin/queue/{id}/position covering reorder scenarios."""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import Episode
from app.models.show import Show
from app.models.transcription_queue import QueueStatus, TranscriptionQueue


@pytest_asyncio.fixture
async def client(auth_admin):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def three_pending_rows():
    """Create show + 3 episodes + 3 pending queue rows at positions 999900/999901/999902.
    Returns dict {a: row_id, b: row_id, c: row_id} and cleans up after.
    """
    created_ids: list[uuid.UUID] = []
    show_id: uuid.UUID | None = None

    async with AsyncSessionFactory() as db:
        show = Show(
            title="Reorder Test",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()
        show_id = show.id

        rows: dict[str, str] = {}
        ep_ids: list[uuid.UUID] = []
        for i, label in enumerate(["a", "b", "c"]):
            ep = Episode(
                show_id=show.id,
                guid=str(uuid.uuid4()),
                title=f"Ep {label}",
                audio_url="https://example.com/a.mp3",
            )
            db.add(ep)
            await db.flush()
            ep_ids.append(ep.id)

            row = TranscriptionQueue(
                episode_id=ep.id,
                show_id=show.id,
                status=QueueStatus.pending,
                position=999900 + i,
                whisper_model="whisper-1",
            )
            db.add(row)
            await db.flush()
            rows[label] = str(row.id)
            created_ids.append(row.id)
        await db.commit()

    yield {"rows": rows, "ep_ids": ep_ids, "show_id": show_id}

    async with AsyncSessionFactory() as db:
        for rid in created_ids:
            await db.execute(delete(TranscriptionQueue).where(TranscriptionQueue.id == rid))
        for eid in ep_ids:
            await db.execute(delete(Episode).where(Episode.id == eid))
        await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


async def _row_position(row_id: str) -> int:
    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(row_id))
        return row.position


@pytest.mark.asyncio
async def test_move_forward(client, three_pending_rows):
    rows = three_pending_rows["rows"]
    resp = await client.patch(
        f"/admin/queue/{rows['c']}/position", json={"position": 999900}
    )
    assert resp.status_code == 200
    assert resp.json()["position"] == 999900
    assert await _row_position(rows["a"]) == 999901
    assert await _row_position(rows["b"]) == 999902
    assert await _row_position(rows["c"]) == 999900


@pytest.mark.asyncio
async def test_move_backward(client, three_pending_rows):
    rows = three_pending_rows["rows"]
    resp = await client.patch(
        f"/admin/queue/{rows['a']}/position", json={"position": 999902}
    )
    assert resp.status_code == 200
    assert resp.json()["position"] == 999902
    assert await _row_position(rows["b"]) == 999900
    assert await _row_position(rows["c"]) == 999901
    assert await _row_position(rows["a"]) == 999902


@pytest.mark.asyncio
async def test_position_clamped_to_max(client, three_pending_rows):
    rows = three_pending_rows["rows"]
    resp = await client.patch(
        f"/admin/queue/{rows['a']}/position", json={"position": 9999999}
    )
    assert resp.status_code == 200
    assert resp.json()["position"] == 999902
    assert await _row_position(rows["a"]) == 999902


@pytest.mark.asyncio
async def test_noop_when_position_unchanged(client, three_pending_rows):
    rows = three_pending_rows["rows"]
    resp = await client.patch(
        f"/admin/queue/{rows['b']}/position", json={"position": 999901}
    )
    assert resp.status_code == 200
    assert await _row_position(rows["a"]) == 999900
    assert await _row_position(rows["b"]) == 999901
    assert await _row_position(rows["c"]) == 999902


@pytest.mark.asyncio
async def test_running_row_returns_409(client, three_pending_rows):
    rows = three_pending_rows["rows"]
    async with AsyncSessionFactory() as db:
        row = await db.get(TranscriptionQueue, uuid.UUID(rows["a"]))
        row.status = QueueStatus.running
        await db.commit()

    resp = await client.patch(
        f"/admin/queue/{rows['a']}/position", json={"position": 999902}
    )
    assert resp.status_code == 409
