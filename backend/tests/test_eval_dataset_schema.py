"""Schema validation tests for golden-set items — covers the eval_mode field
and the conditional expected_episode_ids constraint introduced by the
eval-runner-enumeration-scope change.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.scripts.validate_schema import validate_item  # noqa: E402


VALID_CHUNK_ID = "ep:aaaa1111-1111-1111-1111-111111111111@10.00"
VALID_EP_ID = "aaaa1111-1111-1111-1111-111111111111"


def _base_item() -> dict:
    return {
        "id": "q-test",
        "type": "fact",
        "eval_mode": "chunk_id",
        "question": "Q?",
        "expected_answer_keywords": ["k"],
        "ground_truth_chunk_ids": [VALID_CHUNK_ID],
        "sentinel": True,
        "source_episode_id": VALID_EP_ID,
    }


def test_valid_chunk_id_item_passes():
    assert validate_item(_base_item()) == []


def test_valid_open_set_lenient_item_passes():
    item = _base_item()
    item["eval_mode"] = "open_set_lenient"
    assert validate_item(item) == []


def test_valid_enumeration_item_passes():
    item = _base_item()
    item["eval_mode"] = "enumeration"
    item["ground_truth_chunk_ids"] = []
    item["expected_episode_ids"] = [VALID_EP_ID]
    assert validate_item(item) == []


def test_missing_eval_mode_fails():
    item = _base_item()
    del item["eval_mode"]
    errors = validate_item(item)
    assert any("eval_mode" in e for e in errors), errors


def test_enumeration_with_empty_expected_episode_ids_fails():
    item = _base_item()
    item["eval_mode"] = "enumeration"
    item["ground_truth_chunk_ids"] = []
    item["expected_episode_ids"] = []
    errors = validate_item(item)
    assert any("expected_episode_ids" in e for e in errors), errors


def test_enumeration_without_expected_episode_ids_fails():
    item = _base_item()
    item["eval_mode"] = "enumeration"
    item["ground_truth_chunk_ids"] = []
    errors = validate_item(item)
    assert any("expected_episode_ids" in e for e in errors), errors


def test_chunk_id_with_non_empty_expected_episode_ids_fails():
    item = _base_item()
    item["expected_episode_ids"] = [VALID_EP_ID]
    errors = validate_item(item)
    assert any("expected_episode_ids" in e for e in errors), errors


def test_invalid_eval_mode_value_fails():
    item = _base_item()
    item["eval_mode"] = "something-else"
    errors = validate_item(item)
    assert any("eval_mode" in e or "enum" in e.lower() for e in errors), errors
