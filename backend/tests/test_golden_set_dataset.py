"""Validation test for delivered golden-set datasets.

Loads each `backend/eval/datasets/{slug}.json` (excluding files prefixed with
`_`) and asserts: schema validity, type histogram match, sentinel count.

Currently only `this-not-that-cool.json` is required; once shipped it MUST
keep validating across edits.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest


DATASETS_DIR = Path(__file__).resolve().parents[1] / "eval" / "datasets"
SCHEMA_PATH = DATASETS_DIR / "_schema.json"

# Per spec the initial golden set targets 50 items (10 sentinel + 40 core)
# across 5 types. v2 of `this-not-that-cool.json` came in at 48 items because
# 2 fact-core candidates were dropped during audit (Path A clean) — accepted
# as a quality > quantity trade-off, see project memory.
EXPECTED_TYPE_HISTOGRAM_V2 = {
    "fact": 17,
    "comprehension": 12,
    "cross-episode": 10,
    "negative": 6,
    "code-switch": 3,
}
EXPECTED_TOTAL_V2 = 48
EXPECTED_SENTINEL_COUNT = 10


def _list_dataset_files() -> list[Path]:
    if not DATASETS_DIR.exists():
        return []
    return [p for p in DATASETS_DIR.glob("*.json") if not p.name.startswith("_")]


@pytest.mark.parametrize("path", _list_dataset_files() or [pytest.param(None, marks=pytest.mark.skip(reason="no dataset present yet"))])
def test_dataset_validates_against_schema(path):
    jsonschema = pytest.importorskip("jsonschema")
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    jsonschema.validate(data, schema)


@pytest.mark.parametrize("path", _list_dataset_files() or [pytest.param(None, marks=pytest.mark.skip(reason="no dataset present yet"))])
def test_v2_dataset_has_correct_distribution(path):
    """v2 of the first delivered dataset (this-not-that-cool) must match the
    audited histogram: 48 items total, 10 sentinel, type counts as below."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != "v2":
        pytest.skip(f"{path.name} version != v2, skipping v2 count assertion")

    items = data["items"]
    assert len(items) == EXPECTED_TOTAL_V2, (
        f"{path.name}: expected {EXPECTED_TOTAL_V2} items, got {len(items)}"
    )

    actual = Counter(i["type"] for i in items)
    assert dict(actual) == EXPECTED_TYPE_HISTOGRAM_V2, (
        f"{path.name}: type histogram {dict(actual)} != expected {EXPECTED_TYPE_HISTOGRAM_V2}"
    )

    sentinel_count = sum(1 for i in items if i.get("sentinel"))
    assert sentinel_count == EXPECTED_SENTINEL_COUNT, (
        f"{path.name}: sentinel count {sentinel_count} != {EXPECTED_SENTINEL_COUNT}"
    )
