"""Tests for r3-2-retrieval-fix lever-test env flags:
- RAG_DESCRIPTION_CAP: override DESCRIPTION_CAP
- RAG_SHOW_NAME_FILTER: opt out of show-name term stripping in _build_ts_query

These tests exercise the parse helpers (not full DB / async retrieval) plus
_build_ts_query directly with a monkeypatched show_name_terms.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _reload_rag(monkeypatch, **env):
    """Reload app.services.rag with given env vars set (or removed if None)."""
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import app.services.rag as rag_module
    importlib.reload(rag_module)
    return rag_module


# ─── RAG_DESCRIPTION_CAP ─────────────────────────────────────────────


def test_description_cap_env_unset_uses_in_code_default(monkeypatch, capsys):
    rag = _reload_rag(monkeypatch, RAG_DESCRIPTION_CAP=None)
    assert rag._DESCRIPTION_CAP_RUNTIME == rag.DESCRIPTION_CAP
    # No warning logged
    captured = capsys.readouterr()
    assert "RAG_DESCRIPTION_CAP" not in captured.err


def test_description_cap_env_zero(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_DESCRIPTION_CAP="0")
    assert rag._DESCRIPTION_CAP_RUNTIME == 0


def test_description_cap_env_positive(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_DESCRIPTION_CAP="5")
    assert rag._DESCRIPTION_CAP_RUNTIME == 5


def test_description_cap_malformed_falls_back_with_warning(monkeypatch, capsys):
    rag = _reload_rag(monkeypatch, RAG_DESCRIPTION_CAP="abc")
    assert rag._DESCRIPTION_CAP_RUNTIME == rag.DESCRIPTION_CAP
    captured = capsys.readouterr()
    assert "RAG_DESCRIPTION_CAP" in captured.err
    assert "abc" in captured.err
    assert str(rag.DESCRIPTION_CAP) in captured.err


def test_description_cap_negative_falls_back_with_warning(monkeypatch, capsys):
    rag = _reload_rag(monkeypatch, RAG_DESCRIPTION_CAP="-1")
    assert rag._DESCRIPTION_CAP_RUNTIME == rag.DESCRIPTION_CAP
    captured = capsys.readouterr()
    assert "RAG_DESCRIPTION_CAP" in captured.err


# ─── RAG_SHOW_NAME_FILTER ────────────────────────────────────────────


def test_show_name_filter_env_unset_preserves_strip(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_SHOW_NAME_FILTER=None)
    assert rag._SHOW_NAME_FILTER_ENABLED is True
    monkeypatch.setattr(rag.tokenizer, "get_show_name_terms", lambda: {"這又沒有很屌"})
    # tokenizer.tokenize will jieba the question; we stub it to return predictable tokens
    monkeypatch.setattr(
        rag.tokenizer, "tokenize",
        lambda q: ["節目名", "這又沒有很屌", "是", "怎麼", "來", "的"],
    )
    q = rag._build_ts_query("節目名「這又沒有很屌」是怎麼來的？")
    assert q is not None
    assert "這又沒有很屌" not in q


def test_show_name_filter_env_false_retains_show_name(monkeypatch):
    rag = _reload_rag(monkeypatch, RAG_SHOW_NAME_FILTER="false")
    assert rag._SHOW_NAME_FILTER_ENABLED is False
    monkeypatch.setattr(rag.tokenizer, "get_show_name_terms", lambda: {"這又沒有很屌"})
    monkeypatch.setattr(
        rag.tokenizer, "tokenize",
        lambda q: ["節目名", "這又沒有很屌", "是", "怎麼", "來", "的"],
    )
    q = rag._build_ts_query("節目名「這又沒有很屌」是怎麼來的？")
    assert q is not None
    assert "這又沒有很屌" in q


@pytest.mark.parametrize("val", ["FALSE", "0", "off", "Off"])
def test_show_name_filter_disable_tokens(monkeypatch, val):
    rag = _reload_rag(monkeypatch, RAG_SHOW_NAME_FILTER=val)
    assert rag._SHOW_NAME_FILTER_ENABLED is False


@pytest.mark.parametrize("val", ["true", "1", "yes", "on", "anything", ""])
def test_show_name_filter_non_disable_values_preserve_strip(monkeypatch, val):
    rag = _reload_rag(monkeypatch, RAG_SHOW_NAME_FILTER=val)
    assert rag._SHOW_NAME_FILTER_ENABLED is True


# ─── isolation: reload rag with both env vars set ─────────────────────


def test_both_flags_combined(monkeypatch):
    rag = _reload_rag(
        monkeypatch,
        RAG_DESCRIPTION_CAP="0",
        RAG_SHOW_NAME_FILTER="false",
    )
    assert rag._DESCRIPTION_CAP_RUNTIME == 0
    assert rag._SHOW_NAME_FILTER_ENABLED is False
