"""hyde-retrieval-landing spec tests: resolve_semantic_embedding helper.

Covers the Implementation Contract acceptance criteria:
- (a) flag off -> returns base_vec, used_hyde=False, extra_llm_calls==0
- (b) flag on + LLM ok -> returns HyDE-text embedding, used_hyde==True
- (c) flag on + LLM raises -> fail-open to base_vec, used_hyde==False, no raise
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services import hyde_retrieval  # noqa: E402
from app.services.ai_step_resolver import StepConfig  # noqa: E402

BASE_VEC = [0.1, 0.2, 0.3]
HYDE_VEC = [0.9, 0.9, 0.9]
EMBED_CFG = StepConfig(
    step_key="embedding", step_type="embedding", base_url="http://x",
    api_key="k", model="embed-model", extra_config={},
)
ANSWER_CFG = StepConfig(
    step_key="answer", step_type="chat", base_url="http://x",
    api_key="k", model="chat-model", extra_config={},
)


@pytest.mark.asyncio
async def test_flag_off_returns_base_vec(monkeypatch):
    monkeypatch.setattr(settings, "enable_hyde_retrieval", False)
    # No LLM/embed should be touched on the off path.
    monkeypatch.setattr(
        hyde_retrieval, "get_step_config",
        AsyncMock(side_effect=AssertionError("must not call get_step_config when off")),
    )
    res = await hyde_retrieval.resolve_semantic_embedding(
        db=object(), question="原問句", base_vec=BASE_VEC, embedding_cfg=EMBED_CFG
    )
    assert res.semantic_vec == BASE_VEC
    assert res.used_hyde is False
    assert res.extra_llm_calls == 0
    assert res.hyde_text is None


@pytest.mark.asyncio
async def test_flag_on_success_returns_hyde_vec(monkeypatch):
    monkeypatch.setattr(settings, "enable_hyde_retrieval", True)
    monkeypatch.setattr(
        hyde_retrieval, "get_step_config", AsyncMock(return_value=ANSWER_CFG)
    )
    monkeypatch.setattr(hyde_retrieval, "OpenAI", lambda **kw: object())
    monkeypatch.setattr(
        hyde_retrieval, "_chat", lambda *a, **k: ("講者口吻的假設答案", 12.3)
    )
    monkeypatch.setattr(hyde_retrieval, "embed_texts", lambda texts, cfg: [HYDE_VEC])

    res = await hyde_retrieval.resolve_semantic_embedding(
        db=object(), question="原問句", base_vec=BASE_VEC, embedding_cfg=EMBED_CFG
    )
    assert res.semantic_vec == HYDE_VEC
    assert res.used_hyde is True
    assert res.hyde_text == "講者口吻的假設答案"
    assert res.extra_llm_calls == 1


@pytest.mark.asyncio
async def test_flag_on_llm_error_fails_open(monkeypatch):
    monkeypatch.setattr(settings, "enable_hyde_retrieval", True)
    monkeypatch.setattr(
        hyde_retrieval, "get_step_config", AsyncMock(return_value=ANSWER_CFG)
    )
    monkeypatch.setattr(hyde_retrieval, "OpenAI", lambda **kw: object())

    def _boom(*a, **k):
        raise RuntimeError("LLM exploded")

    monkeypatch.setattr(hyde_retrieval, "_chat", _boom)
    # embed_texts must NOT be reached on the failure path.
    monkeypatch.setattr(
        hyde_retrieval, "embed_texts",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("embed must not run")),
    )

    res = await hyde_retrieval.resolve_semantic_embedding(
        db=object(), question="原問句", base_vec=BASE_VEC, embedding_cfg=EMBED_CFG
    )
    assert res.semantic_vec == BASE_VEC
    assert res.used_hyde is False
