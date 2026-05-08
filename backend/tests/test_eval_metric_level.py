"""Tests for eval runner --metric-level flag (episode vs chunk)."""
from __future__ import annotations

from eval.runners.run import _to_episode_ids, _to_lenient_ids


def test_to_episode_ids_extracts_uuid_from_transcript_chunk_id():
    chunks = [
        "ep:9359c207-1970-4ab4-acce-bf8d44967b68@252.60",
        "ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@180.00",
    ]
    out = _to_episode_ids(chunks)
    assert out == [
        "9359c207-1970-4ab4-acce-bf8d44967b68",
        "c1d87278-7dba-4fb1-930d-c2bd3a3461d2",
    ]


def test_to_episode_ids_handles_description_prefix():
    chunks = ["desc:9359c207-1970-4ab4-acce-bf8d44967b68"]
    out = _to_episode_ids(chunks)
    assert out == ["9359c207-1970-4ab4-acce-bf8d44967b68"]


def test_to_episode_ids_episode_level_match_works_across_sources():
    """Spec scenario: anchor `ep:<E1>@252.60` retrieved via desc:<E1> counts as hit."""
    anchor = ["ep:9359c207-1970-4ab4-acce-bf8d44967b68@252.60"]
    retrieved_desc = ["desc:9359c207-1970-4ab4-acce-bf8d44967b68"]

    # Episode-level: should match
    a_eps = _to_episode_ids(anchor)
    r_eps = _to_episode_ids(retrieved_desc)
    assert any(e in a_eps for e in r_eps)

    # Chunk-level (window=10s): does NOT match (description has start_time=0,
    # anchor at 252.60 → different bucket)
    a_lenient = _to_lenient_ids(anchor, 10.0)
    r_lenient = _to_lenient_ids(retrieved_desc, 10.0)
    assert not any(r in a_lenient for r in r_lenient)
