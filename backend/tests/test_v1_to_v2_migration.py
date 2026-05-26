"""Tests for chat-rag v1 → v2 dataset migration."""
import json
from pathlib import Path

import pytest

from backend.eval.migrations.v1_to_v2_schema import migrate


def _v1_item(item_id: str, **overrides) -> dict:
    base = {
        "id": item_id,
        "design_type": "deep_dive",
        "source": "test",
        "is_multi_turn": False,
        "turns": [
            {
                "question": f"sample question {item_id}",
                "expected_tool_calls_required": ["find_episode_by_ref"],
                "expected_tool_calls_acceptable": [],
                "expected_answer_keywords": ["foo", "bar"],
                "ground_truth_chunk_ids": ["ep:abc@1.00"],
            }
        ],
    }
    base.update(overrides)
    return base


def _v1_dataset(items: list[dict]) -> dict:
    return {
        "version": 1,
        "show_id": "11111111-1111-1111-1111-111111111111",
        "show_slug": "test",
        "created_at": "2026-05-01",
        "items": items,
    }


def test_migration_lossless_for_40_items():
    v1 = _v1_dataset([_v1_item(f"b{i:02d}") for i in range(40)])
    v2 = migrate(v1)
    assert v2["schema_version"] == "2.0"
    assert len(v2["items"]) == 40
    assert {i["id"] for i in v2["items"]} == {f"b{i:02d}" for i in range(40)}


def test_migration_drops_expected_answer_keywords():
    v1 = _v1_dataset([_v1_item("b01")])
    v2 = migrate(v1)
    assert "expected_answer_keywords" not in v2["items"][0]
    assert v2["items"][0]["expected_answer_summary"] == "PENDING AUDIT"


def test_migration_maps_single_tier_ground_truth_to_must():
    v1 = _v1_dataset([_v1_item("b01")])
    v2 = migrate(v1)
    item = v2["items"][0]
    assert item["ground_truth_chunk_ids_must"] == ["ep:abc@1.00"]
    assert item["ground_truth_chunk_ids_either"] is None
    assert item["ground_truth_chunk_ids_acceptable"] is None


def test_migration_audit_status_defaults_pending():
    v1 = _v1_dataset([_v1_item("b01"), _v1_item("b22")])
    v2 = migrate(v1)
    for item in v2["items"]:
        assert item["audit_status"] == "pending"


def test_migration_fails_loudly_on_missing_question():
    bad = _v1_item("bX")
    bad["turns"][0].pop("question")
    v1 = _v1_dataset([bad])
    with pytest.raises(KeyError, match="question"):
        migrate(v1)


def test_migration_fails_loudly_on_missing_design_type():
    bad = _v1_item("bX")
    bad.pop("design_type")
    v1 = _v1_dataset([bad])
    with pytest.raises(KeyError, match="design_type"):
        migrate(v1)


def test_migration_handles_multi_turn():
    mt = {
        "id": "mt01",
        "design_type": "multi_turn",
        "source": "test",
        "is_multi_turn": True,
        "turns": [
            {"question": "t1?", "expected_tool_calls_required": ["find_episodes_by_topic"]},
            {"question": "t2?", "carry_note": "t1.enumeration_episodes[2] DESC"},
        ],
    }
    v1 = _v1_dataset([mt])
    v2 = migrate(v1)
    item = v2["items"][0]
    assert item["is_multi_turn"] is True
    assert len(item["turns"]) == 2
    assert item["turns"][1]["carry_from"] == "t1.enumeration_episodes[2] DESC"
    assert item["turns"][1]["ordinal_resolution_check"] is True
