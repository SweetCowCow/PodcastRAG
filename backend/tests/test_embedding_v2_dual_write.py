"""r3-4 spec tests: dual-write helper `embed_texts_dual`.

Covers Scenario "dual-write during transition":
  (a) EMBEDDING_DUAL_WRITE=true -> both legacy + v2 vectors populated
  (b) EMBEDDING_DUAL_WRITE=false -> only v2 populated, legacy returns None
  (c) v2 API failure -> legacy still returned, v2 = None (graceful)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ai_step_resolver import StepConfig
from app.services.embedding import (
    LEGACY_EMBEDDING_MODEL,
    V2_EMBEDDING_DIM,
    V2_EMBEDDING_MODEL,
    embed_texts_dual,
)


def _fake_cfg() -> StepConfig:
    return StepConfig(
        step_key="embedding",
        step_type="embedding",
        base_url="https://api.openai.com/v1",
        api_key="sk-fake",
        model="text-embedding-3-small",
        extra_config={},
    )


def test_models_have_expected_constants():
    assert LEGACY_EMBEDDING_MODEL == "text-embedding-3-small"
    assert V2_EMBEDDING_MODEL == "text-embedding-3-large"
    assert V2_EMBEDDING_DIM == 3072


def test_dual_write_default_on_returns_both(monkeypatch):
    monkeypatch.delenv("EMBEDDING_DUAL_WRITE", raising=False)
    legacy_fake = [[0.1] * 1536]
    v2_fake = [[0.2] * 3072]

    def fake_embed_with_retry(client, batch, model):
        if model == LEGACY_EMBEDDING_MODEL:
            return legacy_fake
        if model == V2_EMBEDDING_MODEL:
            return v2_fake
        raise AssertionError(f"unexpected model {model}")

    with patch(
        "app.services.embedding._embed_with_retry", side_effect=fake_embed_with_retry
    ):
        legacy, v2 = embed_texts_dual(["hello"], _fake_cfg())
    assert legacy == legacy_fake
    assert v2 == v2_fake


def test_dual_write_disabled_skips_legacy(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DUAL_WRITE", "false")
    v2_fake = [[0.2] * 3072]
    calls: list[str] = []

    def fake_embed_with_retry(client, batch, model):
        calls.append(model)
        if model == V2_EMBEDDING_MODEL:
            return v2_fake
        raise AssertionError(f"legacy must not be called when dual-write off")

    with patch(
        "app.services.embedding._embed_with_retry", side_effect=fake_embed_with_retry
    ):
        legacy, v2 = embed_texts_dual(["hello"], _fake_cfg())

    assert legacy is None
    assert v2 == v2_fake
    assert LEGACY_EMBEDDING_MODEL not in calls


def test_v2_failure_returns_legacy_only(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DUAL_WRITE", "true")
    legacy_fake = [[0.1] * 1536]

    def fake_embed_with_retry(client, batch, model):
        if model == LEGACY_EMBEDDING_MODEL:
            return legacy_fake
        raise RuntimeError("v2 model API down")

    with patch(
        "app.services.embedding._embed_with_retry", side_effect=fake_embed_with_retry
    ):
        legacy, v2 = embed_texts_dual(["hello"], _fake_cfg())

    assert legacy == legacy_fake
    assert v2 is None  # graceful, per spec


def test_legacy_failure_keeps_v2(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DUAL_WRITE", "true")
    v2_fake = [[0.2] * 3072]

    def fake_embed_with_retry(client, batch, model):
        if model == V2_EMBEDDING_MODEL:
            return v2_fake
        raise RuntimeError("legacy model API down")

    with patch(
        "app.services.embedding._embed_with_retry", side_effect=fake_embed_with_retry
    ):
        legacy, v2 = embed_texts_dual(["hello"], _fake_cfg())

    assert legacy is None
    assert v2 == v2_fake


def test_empty_input_returns_empty_lists():
    legacy, v2 = embed_texts_dual([], _fake_cfg())
    assert legacy == []
    assert v2 == []
