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
SCHEMA_V2_PATH = DATASETS_DIR / "_chat_rag_schema_v2.json"

# r3-5-disable-routing audit (2026-05-13): removed 36 LLM-auto items
# (`thisno-core-*`) whose verified bad-question rate was ≥75%. The dataset now
# contains only the 10 hand-crafted sentinel items (q01-q10). Future LLM-auto
# items SHALL stage through `_pending_review.json` per build_golden_set.py.
EXPECTED_TYPE_HISTOGRAM_V2 = {
    "fact": 3,
    "comprehension": 2,
    "cross-episode": 2,
    "negative": 2,
    "code-switch": 1,
}
EXPECTED_TOTAL_V2 = 10
EXPECTED_SENTINEL_COUNT = 10


def _list_dataset_files() -> list[Path]:
    if not DATASETS_DIR.exists():
        return []
    return [p for p in DATASETS_DIR.glob("*.json") if not p.name.startswith("_")]


@pytest.mark.parametrize("path", _list_dataset_files() or [pytest.param(None, marks=pytest.mark.skip(reason="no dataset present yet"))])
def test_dataset_validates_against_schema(path):
    jsonschema = pytest.importorskip("jsonschema")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    # v2-format datasets (chat-rag golden v2) declare schema_version "2.0";
    # everything else is validated against the original v1 schema.
    schema_path = SCHEMA_V2_PATH if data.get("schema_version") == "2.0" else SCHEMA_PATH
    with schema_path.open(encoding="utf-8") as f:
        schema = json.load(f)
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


# ─── r3-5-disable-routing: LLM-auto staging discipline ────────────────


@pytest.mark.parametrize(
    "path",
    _list_dataset_files() or [pytest.param(None, marks=pytest.mark.skip(reason="no dataset present yet"))],
)
def test_no_thisno_core_ids_without_audit_metadata(path):
    """After the 2026-05-13 audit, items whose id starts with `thisno-core-`
    SHALL NOT exist in the main dataset unless the dataset's `audit` metadata
    records that they passed human review (per the staging discipline in
    backend/eval/scripts/build_golden_set.py)."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    offending = [
        i for i in data.get("items", [])
        if isinstance(i.get("id"), str) and i["id"].startswith("thisno-core-")
    ]
    if not offending:
        return  # clean state — no work to do

    audit = data.get("audit") or {}
    # If the dataset re-introduces any thisno-core-* id, the top-level audit
    # block MUST record a non-empty reviewed_by + reviewed_at attesting the
    # human-review step described in the rag-eval-dataset spec.
    reviewed_by = audit.get("reviewed_by")
    reviewed_at = audit.get("reviewed_at")
    assert reviewed_by and reviewed_at, (
        f"{path.name}: contains {len(offending)} `thisno-core-*` items but "
        f"`audit.reviewed_by` / `audit.reviewed_at` not set — staging discipline "
        f"violated (see rag-eval-dataset spec, r3-5-disable-routing)."
    )
