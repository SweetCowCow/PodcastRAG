"""r3-4 spec tests: RAG_USE_EMBEDDING_V2 env flag.

Covers:
- flag off (default) -> SQL targets legacy `embedding` column + vector cast
- flag on -> SQL targets `embedding_v2` column + halfvec(3072) cast
- dim mismatch raises a hard error (no silent fallback)
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _reload_rag(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import app.services.rag as rag_module
    importlib.reload(rag_module)
    return rag_module


def test_flag_unset_targets_legacy_embedding(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2=None)
    assert rag._USE_EMBEDDING_V2 is False
    assert rag._EXPECTED_QUERY_DIM == 1536
    sql = rag._resolve_embed_placeholders(rag._TRANSCRIPT_SEMANTIC_ONLY_SQL)
    assert "c.embedding <=> CAST(:query_embedding AS vector)" in sql
    assert "embedding_v2" not in sql
    assert "halfvec" not in sql


def test_flag_true_targets_embedding_v2_with_halfvec_cast(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2="true")
    assert rag._USE_EMBEDDING_V2 is True
    assert rag._EXPECTED_QUERY_DIM == 3072
    sql = rag._resolve_embed_placeholders(rag._TRANSCRIPT_SEMANTIC_ONLY_SQL)
    assert "c.embedding_v2::halfvec(3072)" in sql
    assert "CAST(:query_embedding AS halfvec(3072))" in sql
    # Make sure we didn't accidentally leave a raw vector cast in v2 path.
    assert "AS vector)" not in sql


def test_flag_true_applies_to_description_sql(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2="1")
    sql = rag._resolve_embed_placeholders(rag._DESC_SEMANTIC_ONLY_SQL)
    assert "d.embedding_v2::halfvec(3072)" in sql
    assert "d.embedding_v2 IS NOT NULL" in sql


def test_flag_true_applies_to_route_sql(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2="on")
    sql = rag._resolve_embed_placeholders(rag._ROUTE_EPISODES_SQL)
    assert "d.embedding_v2::halfvec(3072)" in sql


def test_flag_off_with_explicit_false(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2="false")
    assert rag._USE_EMBEDDING_V2 is False


def test_flag_off_with_random_value(monkeypatch):
    """Any value other than truthy tokens leaves the flag off (conservative)."""
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2="maybe")
    assert rag._USE_EMBEDDING_V2 is False


def test_dim_mismatch_raises_hard_error(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2="true")
    # Active path expects 3072; hand it a 1536 embedding -> hard error.
    with pytest.raises(RuntimeError, match="query embedding dim 1536"):
        rag._validate_query_dim([0.1] * 1536)


def test_dim_match_passes_through(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2="true")
    rag._validate_query_dim([0.1] * 3072)  # no raise


def test_dim_match_legacy_passes(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2=None)
    rag._validate_query_dim([0.1] * 1536)


def test_dim_legacy_3072_raises(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2=None)
    with pytest.raises(RuntimeError, match="query embedding dim 3072"):
        rag._validate_query_dim([0.1] * 3072)


def test_empty_embedding_skips_validation(monkeypatch):
    """No-op when caller passes an empty list (e.g. eval scripts probing)."""
    rag = _reload_rag(monkeypatch, RAG_USE_EMBEDDING_V2="true")
    rag._validate_query_dim([])
