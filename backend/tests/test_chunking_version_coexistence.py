"""Unit tests for chunking-version-coexistence.

These avoid live DB and instead assert on:
  - ChunkHit dataclass schema
  - SQL templates carrying the new SELECT columns
  - SQLAlchemy model unique constraint
  - Migration revision metadata
  - description_indexer signature accepts (chunking_version, chunk_index)
  - cleanup CLI dry-run / safeguard behaviour via subprocess + monkeypatch
"""
from __future__ import annotations

import inspect

from app.models.episode_description_chunk import EpisodeDescriptionChunk
from app.services import description_indexer
from app.services.rag import (
    _DESC_RRF_SQL,
    _DESC_SEMANTIC_ONLY_SQL,
    ChunkHit,
)


def test_chunk_hit_defaults_to_v1_chunk_index_zero():
    """Every existing ChunkHit construction must keep working without
    explicitly passing the new fields (transcript hits, eval fixtures, …)."""
    import uuid as _uuid

    hit = ChunkHit(
        episode_id=_uuid.uuid4(),
        episode_title="t",
        start_time=0.0,
        end_time=1.0,
        text="x",
    )
    assert hit.chunking_version == 1
    assert hit.chunk_index == 0


def test_chunk_hit_carries_explicit_version_and_index():
    import uuid as _uuid

    hit = ChunkHit(
        episode_id=_uuid.uuid4(),
        episode_title="t",
        start_time=0.0,
        end_time=0.0,
        text="x",
        source="description",
        chunking_version=2,
        chunk_index=7,
    )
    assert hit.chunking_version == 2
    assert hit.chunk_index == 7


def test_desc_rrf_sql_selects_chunking_version_and_index():
    """retrieval_descriptions hybrid path must SELECT both fields so the
    Python adapter can populate ChunkHit."""
    assert "d.chunking_version" in _DESC_RRF_SQL
    assert "d.chunk_index" in _DESC_RRF_SQL


def test_desc_semantic_only_sql_selects_chunking_version_and_index():
    assert "d.chunking_version" in _DESC_SEMANTIC_ONLY_SQL
    assert "d.chunk_index" in _DESC_SEMANTIC_ONLY_SQL


def test_desc_rrf_sql_does_not_filter_by_chunking_version():
    """v1 + v2 must share the RRF pool — no WHERE clause filters them apart."""
    assert "chunking_version =" not in _DESC_RRF_SQL.replace(
        "d.chunking_version,", ""
    )
    assert "chunking_version =" not in _DESC_SEMANTIC_ONLY_SQL.replace(
        "d.chunking_version,", ""
    )


def test_episode_description_chunk_has_composite_unique():
    """SQLAlchemy model must declare the composite unique used by UPSERT."""
    constraints = list(EpisodeDescriptionChunk.__table__.constraints)
    uq_names = [c.name for c in constraints if hasattr(c, "name") and c.name]
    assert "uq_desc_chunk_episode_version_index" in uq_names

    # The episode_id column should NOT carry a single-column unique anymore.
    ep_col = EpisodeDescriptionChunk.__table__.c.episode_id
    assert ep_col.unique is not True


def test_episode_description_chunk_has_versioning_columns():
    cols = {c.name: c for c in EpisodeDescriptionChunk.__table__.columns}
    assert "chunking_version" in cols
    assert "chunk_index" in cols
    assert cols["chunking_version"].nullable is False
    assert cols["chunk_index"].nullable is False
    # server_default backfills existing rows to (1, 0) — required so the
    # migration's `NOT NULL DEFAULT 1` matches the model.
    assert cols["chunking_version"].server_default is not None
    assert cols["chunk_index"].server_default is not None


def test_indexer_accepts_chunking_version_and_chunk_index_kwargs():
    sig = inspect.signature(description_indexer.build_description_index_for_episode)
    assert "chunking_version" in sig.parameters
    assert "chunk_index" in sig.parameters
    # Backward compatibility — existing callers don't pass these.
    assert sig.parameters["chunking_version"].default == 1
    assert sig.parameters["chunk_index"].default == 0
    # Keyword-only (so positional callers can't accidentally swap into them).
    assert sig.parameters["chunking_version"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["chunk_index"].kind is inspect.Parameter.KEYWORD_ONLY


def test_migration_t8_revision_targets_s7():
    """Smoke-check alembic revision metadata so we don't accidentally
    rebase onto the wrong parent."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision("t8a9b0c1d2e3")
    assert rev is not None
    assert rev.down_revision == "s7f8a9b0c1d2"


def test_cleanup_script_safeguard_blocks_missing_v2(monkeypatch, capsys):
    """Running cleanup --execute (no --force) against a show where some
    episodes lack v2 must exit 2 without issuing DELETEs."""
    import asyncio
    import sys
    import uuid as _uuid

    from scripts import cleanup_v1_description_chunks as cl

    fake_stats = [
        cl.EpisodeCleanupStats(
            episode_id=_uuid.uuid4(), title="ep1", v1_chunks=1, v2_chunks=5
        ),
        cl.EpisodeCleanupStats(
            episode_id=_uuid.uuid4(), title="ep2", v1_chunks=1, v2_chunks=0
        ),
    ]

    async def fake_collect(show_id):
        return fake_stats

    delete_called = {"n": 0}

    async def fake_delete(stats):
        delete_called["n"] += 1
        return (0, 0)

    monkeypatch.setattr(cl, "_collect_stats", fake_collect)
    monkeypatch.setattr(cl, "_execute_delete", fake_delete)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cleanup_v1_description_chunks.py",
            "--show-id",
            str(_uuid.uuid4()),
            "--execute",
        ],
    )
    rc = cl.main()
    assert rc == 2
    assert delete_called["n"] == 0
    captured = capsys.readouterr()
    assert "Refusing to delete v1" in captured.out


def test_cleanup_script_dry_run_does_not_delete(monkeypatch, capsys):
    import sys
    import uuid as _uuid

    from scripts import cleanup_v1_description_chunks as cl

    fake_stats = [
        cl.EpisodeCleanupStats(
            episode_id=_uuid.uuid4(), title="ep1", v1_chunks=1, v2_chunks=5
        ),
    ]

    async def fake_collect(show_id):
        return fake_stats

    delete_called = {"n": 0}

    async def fake_delete(stats):
        delete_called["n"] += 1
        return (1, 1)

    monkeypatch.setattr(cl, "_collect_stats", fake_collect)
    monkeypatch.setattr(cl, "_execute_delete", fake_delete)
    monkeypatch.setattr(
        sys,
        "argv",
        ["cleanup_v1_description_chunks.py", "--show-id", str(_uuid.uuid4())],
    )
    rc = cl.main()
    assert rc == 0
    assert delete_called["n"] == 0
    captured = capsys.readouterr()
    assert "dry-run" in captured.out
