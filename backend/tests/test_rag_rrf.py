"""Unit tests for RRF math + import scan for forbidden retrieval libs."""
from __future__ import annotations

import pathlib
import re

from app.services import rag


def test_rrf_constants_match_design():
    assert rag.RRF_K == 60
    assert rag.RRF_PER_SIDE == 50
    assert rag.RETRIEVAL_TOP_K == 8


def _rrf(rank_s: int | None, rank_l: int | None, k: int = 60) -> float:
    s = 1.0 / (k + (rank_s if rank_s is not None else 999))
    l_ = 1.0 / (k + (rank_l if rank_l is not None else 999))
    return s + l_


def test_rrf_math_spec_example():
    # Spec example: chunk A (rank_s=3, rank_l=25) vs chunk B (rank_s=50, rank_l=1)
    rrf_a = _rrf(3, 25)
    rrf_b = _rrf(50, 1)
    assert rrf_a == 1 / 63 + 1 / 85
    assert rrf_b == 1 / 110 + 1 / 61
    # With k=60 the semantic-rank-3 contribution outweighs B's lexical-rank-1.
    assert rrf_a > rrf_b


def test_rrf_one_side_only_uses_placeholder_999():
    # Chunk C: semantic rank 10, absent from lexical → 1/(60+10) + 1/(60+999)
    rrf_c = _rrf(10, None)
    assert abs(rrf_c - (1 / 70 + 1 / 1059)) < 1e-12


def test_build_ts_query_filters_punctuation_and_short():
    # Reset tokenizer state so prior tests' adds don't leak.
    from app.services import tokenizer
    tokenizer.reset_for_tests()

    # Stock jieba with no custom dict — tokens depend on jieba but the helper
    # should drop punctuation-only and single-character non-CJK tokens.
    out = rag._build_ts_query("hello world! 你好嗎")
    assert out is not None
    assert "&" in out
    # No bare punctuation
    assert "!" not in out


def test_build_ts_query_returns_none_for_pure_punctuation():
    from app.services import tokenizer
    tokenizer.reset_for_tests()

    assert rag._build_ts_query("!!!") is None
    assert rag._build_ts_query("") is None
    assert rag._build_ts_query("   ") is None


def test_hit_key_format_for_each_source():
    import uuid as _uuid

    transcript_hit = rag.ChunkHit(
        episode_id=_uuid.UUID("00000000-0000-0000-0000-000000000001"),
        episode_title="t",
        start_time=153.42,
        end_time=160.0,
        text="x",
        source="transcript",
    )
    assert rag._hit_key(transcript_hit) == (
        "ep:00000000-0000-0000-0000-000000000001@153.42"
    )

    desc_hit = rag.ChunkHit(
        episode_id=_uuid.UUID("00000000-0000-0000-0000-000000000002"),
        episode_title="t",
        start_time=0.0,
        end_time=0.0,
        text="x",
        source="description",
    )
    assert rag._hit_key(desc_hit) == "desc:00000000-0000-0000-0000-000000000002"


def test_no_external_retrieval_lib_imported():
    """Spec scenario: no llama_index / langchain / haystack imports anywhere."""
    backend_root = pathlib.Path(__file__).resolve().parent.parent / "app"
    forbidden = re.compile(
        r"^\s*(?:from|import)\s+(llama_index|langchain|langchain_\w+|haystack)\b"
    )
    offenders: list[str] = []
    for path in backend_root.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if forbidden.match(line):
                offenders.append(f"{path}: {line}")
    assert offenders == [], f"Forbidden retrieval lib imports found: {offenders}"
