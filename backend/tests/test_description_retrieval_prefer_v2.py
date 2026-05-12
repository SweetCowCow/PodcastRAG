"""Unit tests for `description-retrieval-prefer-v2`.

These assert structural properties of the three modified SQL templates
in `backend/app/services/rag.py` plus behavioural shape via a stub
AsyncSession. They cover the four scenarios from the spec
(`openspec/changes/description-retrieval-prefer-v2/specs/rag-query/spec.md`):

  - same-episode v2 hides v1 from the pool
  - episode without v2 falls back to v1
  - show without any v2 chunks degenerates to pre-coexistence behaviour
  - routing returns k *distinct* episode_ids (not k chunk rows) and
    prefers v2 ranking when present

No live DB is required — these run alongside the existing
`test_chunking_version_coexistence.py` structural suite. End-to-end
recall behaviour is validated via the prod eval against
`backend/eval/datasets/this-not-that-cool.json` (see case study).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.sql import text

from app.services.rag import (
    _DESC_RRF_SQL,
    _DESC_SEMANTIC_ONLY_SQL,
    _ROUTE_EPISODES_SQL,
    retrieve_descriptions,
    route_episodes,
)


# ─── Structural assertions (Scenario 1-4, SQL shape) ────────────────────


def test_desc_rrf_sql_carries_prefer_v2_clause_in_both_ctes():
    """Both semantic and lexical CTEs must filter by the prefer-v2 policy.
    Without this, ts_rank short-chunk bias floods the lexical CTE with v1
    long rows and evicts v2 (Phase 2 root cause #1/#2)."""
    # Two CTEs, two NOT IN sub-selects scoped by show_id.
    formatted = _DESC_RRF_SQL.format(episode_filter="")
    assert formatted.count("d.chunking_version = 2") >= 2
    assert formatted.count("d.episode_id NOT IN (") >= 2
    # Sub-selects must constrain by show to keep the semi-join cheap.
    assert formatted.count("e2.show_id = :show_id") >= 2


def test_desc_semantic_only_sql_carries_prefer_v2_clause():
    formatted = _DESC_SEMANTIC_ONLY_SQL.format(episode_filter="")
    assert "d.chunking_version = 2" in formatted
    assert "d.episode_id NOT IN (" in formatted
    assert "e2.show_id = :show_id" in formatted


def test_route_episodes_sql_returns_distinct_episode_ids():
    """`_ROUTE_EPISODES_SQL` must use DISTINCT ON + outer LIMIT wrapper
    so `k` is k distinct episodes, not k chunk rows (Phase 2 root cause
    #3 — top-10 chunk rows fit in 4-5 episodes once v1+v2 coexist)."""
    assert "DISTINCT ON (e.id)" in _ROUTE_EPISODES_SQL
    # Outer wrapper sort by dist then LIMIT
    assert "ORDER BY dist ASC" in _ROUTE_EPISODES_SQL
    assert "LIMIT :k" in _ROUTE_EPISODES_SQL


def test_route_episodes_sql_prefers_v2():
    assert "d.chunking_version = 2" in _ROUTE_EPISODES_SQL
    assert "d.episode_id NOT IN (" in _ROUTE_EPISODES_SQL
    assert "e2.show_id = :show_id" in _ROUTE_EPISODES_SQL


def test_modified_sqls_parameter_binding_compiles():
    """SQLAlchemy text() must accept the SQL with the formatted
    `{episode_filter}` placeholder (empty + non-empty). If the prefer-v2
    sub-select accidentally introduces a new bind name or quoting issue,
    this catches it before deploy."""
    assert text(_DESC_RRF_SQL.format(episode_filter="")) is not None
    assert (
        text(
            _DESC_RRF_SQL.format(
                episode_filter="AND e.id = ANY(CAST(:episode_ids AS uuid[]))"
            )
        )
        is not None
    )
    assert text(_DESC_SEMANTIC_ONLY_SQL.format(episode_filter="")) is not None
    assert text(_ROUTE_EPISODES_SQL) is not None


def test_no_new_bind_params_introduced():
    """Prefer-v2 must reuse :show_id — adding a new bind (e.g.
    :show_id_v2) would force the call-site to bind it explicitly. Keep
    binding surface stable."""
    formatted = _DESC_RRF_SQL.format(episode_filter="")
    # Allowed binds.
    allowed = {":query_embedding", ":show_id", ":per_side", ":ts_query", ":rrf_k", ":k"}
    # Find all ":<word>" bind references.
    import re

    found = set(re.findall(r":[A-Za-z_][A-Za-z_0-9]*", formatted))
    extra = found - allowed
    assert not extra, f"unexpected bind params introduced: {extra}"


# ─── Behavioural tests using a stub AsyncSession ────────────────────────
#
# These do not exercise a real PG planner — they verify the Python
# wrapper passes the right params, the right SQL template, and lifts row
# mappings into ChunkHit. Real prefer-v2 filtering is exercised by the
# prod smoke (see deploy step) and the eval pipeline; we cannot run real
# PG/pgvector here because CI doesn't have it.


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return iter(self._rows)


class _FakeSession:
    """Records the last SQL string + params, returns canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.last_sql: str | None = None
        self.last_params: dict | None = None

    async def execute(self, sql, params):
        # SQLAlchemy text() stringifies to its source string.
        self.last_sql = str(sql)
        self.last_params = params
        return _FakeMappings(self._rows)


@pytest.mark.asyncio
async def test_retrieve_descriptions_uses_rrf_sql_when_question_present():
    show_id = uuid.uuid4()
    ep_id = uuid.uuid4()
    rows = [
        {
            "chunk_id": uuid.uuid4(),
            "rrf_score": 0.5,
            "text": "v2 short chunk",
            "chunking_version": 2,
            "chunk_index": 2,
            "episode_id": ep_id,
            "episode_title": "EP1",
        }
    ]
    fake = _FakeSession(rows)
    hits = await retrieve_descriptions(
        fake,  # type: ignore[arg-type]
        show_id=show_id,
        query_embedding=[0.0] * 1536,
        question="節目名來源",
        k=5,
    )
    assert fake.last_sql is not None
    # Must use RRF SQL (has WITH semantic) and carry prefer-v2 filter.
    assert "WITH semantic AS" in fake.last_sql
    assert "d.chunking_version = 2" in fake.last_sql
    assert "d.episode_id NOT IN" in fake.last_sql
    # Hit must propagate chunking_version=2 (Scenario 1).
    assert len(hits) == 1
    assert hits[0].chunking_version == 2
    assert hits[0].source == "description"


@pytest.mark.asyncio
async def test_retrieve_descriptions_uses_semantic_only_when_no_ts_query():
    show_id = uuid.uuid4()
    rows = [
        {
            "chunk_id": uuid.uuid4(),
            "distance": 0.3,
            "text": "v1 fallback",
            "chunking_version": 1,
            "chunk_index": 0,
            "episode_id": uuid.uuid4(),
            "episode_title": "EP2",
        }
    ]
    fake = _FakeSession(rows)
    # Empty question → semantic-only path.
    hits = await retrieve_descriptions(
        fake,  # type: ignore[arg-type]
        show_id=show_id,
        query_embedding=[0.0] * 1536,
        question="",
        k=5,
    )
    assert fake.last_sql is not None
    assert "WITH semantic AS" not in fake.last_sql
    # Prefer-v2 still applies on the fallback path (Scenario 2/3).
    assert "d.chunking_version = 2" in fake.last_sql
    assert hits[0].chunking_version == 1


@pytest.mark.asyncio
async def test_route_episodes_passes_show_and_returns_distinct_ids():
    show_id = uuid.uuid4()
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    rows = [
        {"episode_id": e1},
        {"episode_id": e2},
    ]
    fake = _FakeSession(rows)
    result = await route_episodes(
        fake,  # type: ignore[arg-type]
        show_id=show_id,
        query_embedding=[0.0] * 1536,
        k=2,
    )
    assert result == [e1, e2]
    assert fake.last_params is not None
    assert fake.last_params["show_id"] == show_id
    assert fake.last_params["k"] == 2
    # The SQL itself enforces DISTINCT ON (e.id) — guarded structurally
    # in test_route_episodes_sql_returns_distinct_episode_ids.
    assert "DISTINCT ON (e.id)" in fake.last_sql


@pytest.mark.asyncio
async def test_route_episodes_signature_unchanged():
    """`route_episodes` must keep its signature so callers don't need
    updates after the SQL rewrite (Task 2.3)."""
    import inspect

    sig = inspect.signature(route_episodes)
    params = list(sig.parameters)
    assert params == ["db", "show_id", "query_embedding", "k"]
