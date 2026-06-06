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


class _Hit:
    """Minimal ChunkHit stand-in — lexical_overlap_ratio only reads `.text`."""

    def __init__(self, text: str) -> None:
        self.text = text


def test_overlap_all_tokens_present():
    q = "中老年開工和年輕人的差異"
    # corpus literally contains the question → every token is a substring.
    ratio = hyde_retrieval.lexical_overlap_ratio(q, [_Hit("聊到" + q + "這件事")])
    assert ratio == pytest.approx(1.0)


def test_overlap_no_tokens_present():
    q = "中老年開工和年輕人的差異"
    ratio = hyde_retrieval.lexical_overlap_ratio(
        q, [_Hit("今天天氣很好我們去公園散步吃冰")]
    )
    assert ratio == pytest.approx(0.0)


def test_overlap_empty_hits_no_div_by_zero():
    assert hyde_retrieval.lexical_overlap_ratio("任何問題", []) == 0.0


def _make_retrieve(base_hits, hyde_hits):
    """Build a retrieve closure + call recorder. First call (base_vec) returns
    base_hits; subsequent calls return hyde_hits."""
    calls = {"vecs": []}

    async def _retrieve(sem_vec):
        calls["vecs"].append(sem_vec)
        return base_hits if len(calls["vecs"]) == 1 else hyde_hits

    return _retrieve, calls


def _mock_hyde_generation(monkeypatch, *, hyde_vec=HYDE_VEC, raises=False):
    monkeypatch.setattr(settings, "enable_hyde_retrieval", True)
    monkeypatch.setattr(
        hyde_retrieval, "get_step_config", AsyncMock(return_value=ANSWER_CFG)
    )
    monkeypatch.setattr(hyde_retrieval, "OpenAI", lambda **kw: object())
    if raises:
        def _boom(*a, **k):
            raise RuntimeError("LLM exploded")
        monkeypatch.setattr(hyde_retrieval, "_chat", _boom)
    else:
        monkeypatch.setattr(
            hyde_retrieval, "_chat", lambda *a, **k: ("講者口吻假設答案", 5.0)
        )
        monkeypatch.setattr(
            hyde_retrieval, "embed_texts", lambda texts, cfg: [hyde_vec]
        )


@pytest.mark.asyncio
async def test_conditional_high_overlap_skips_hyde(monkeypatch):
    q = "中老年開工和年輕人的差異"
    base_hits = [_Hit("聊到" + q + "這段")]  # overlap ~1.0 >= 0.3
    # get_step_config must NOT be touched — HyDE must not run on high overlap.
    monkeypatch.setattr(settings, "enable_hyde_retrieval", True)
    monkeypatch.setattr(settings, "hyde_mismatch_overlap_threshold", 0.3)
    monkeypatch.setattr(
        hyde_retrieval, "get_step_config",
        AsyncMock(side_effect=AssertionError("HyDE must not run on high overlap")),
    )
    retrieve, calls = _make_retrieve(base_hits, [_Hit("不應出現")])

    hits, res = await hyde_retrieval.resolve_chunk_hits_conditional(
        db=object(), question=q, base_vec=BASE_VEC, embedding_cfg=EMBED_CFG,
        retrieve=retrieve,
    )
    assert hits == base_hits
    assert res.used_hyde is False
    assert res.conditional_mode is True
    assert res.triggered_by_mismatch is False
    assert res.overlap_ratio == pytest.approx(1.0)
    assert len(calls["vecs"]) == 1  # only the base recall ran


@pytest.mark.asyncio
async def test_conditional_low_overlap_triggers_hyde_second_stage(monkeypatch):
    q = "中老年開工和年輕人的差異"
    base_hits = [_Hit("今天天氣很好去公園散步")]  # overlap ~0.0 < 0.3
    hyde_hits = [_Hit("HyDE 第二輪召回結果")]
    monkeypatch.setattr(settings, "hyde_mismatch_overlap_threshold", 0.3)
    _mock_hyde_generation(monkeypatch)
    retrieve, calls = _make_retrieve(base_hits, hyde_hits)

    hits, res = await hyde_retrieval.resolve_chunk_hits_conditional(
        db=object(), question=q, base_vec=BASE_VEC, embedding_cfg=EMBED_CFG,
        retrieve=retrieve,
    )
    assert hits == hyde_hits
    assert res.used_hyde is True
    assert res.conditional_mode is True
    assert res.triggered_by_mismatch is True
    assert res.overlap_ratio == pytest.approx(0.0)
    assert calls["vecs"] == [BASE_VEC, HYDE_VEC]  # base then HyDE recall


@pytest.mark.asyncio
async def test_conditional_hyde_failure_falls_open_to_base_hits(monkeypatch):
    q = "中老年開工和年輕人的差異"
    base_hits = [_Hit("今天天氣很好去公園散步")]  # mismatch → tries HyDE
    monkeypatch.setattr(settings, "hyde_mismatch_overlap_threshold", 0.3)
    _mock_hyde_generation(monkeypatch, raises=True)
    retrieve, calls = _make_retrieve(base_hits, [_Hit("不應出現")])

    hits, res = await hyde_retrieval.resolve_chunk_hits_conditional(
        db=object(), question=q, base_vec=BASE_VEC, embedding_cfg=EMBED_CFG,
        retrieve=retrieve,
    )
    assert hits == base_hits  # fail-open to stage-1 result
    assert res.used_hyde is False
    assert res.triggered_by_mismatch is False
    assert len(calls["vecs"]) == 1  # second recall never ran


@pytest.mark.asyncio
async def test_conditional_overlap_error_falls_open(monkeypatch):
    base_hits = [_Hit("天氣晴")]
    monkeypatch.setattr(
        hyde_retrieval, "lexical_overlap_ratio",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("overlap boom")),
    )
    retrieve, calls = _make_retrieve(base_hits, [_Hit("x")])

    hits, res = await hyde_retrieval.resolve_chunk_hits_conditional(
        db=object(), question="任何問題", base_vec=BASE_VEC, embedding_cfg=EMBED_CFG,
        retrieve=retrieve,
    )
    assert hits == base_hits
    assert res.used_hyde is False
    assert res.overlap_ratio is None
    assert len(calls["vecs"]) == 1


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
