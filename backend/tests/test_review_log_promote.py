"""Unit tests for review_log.py + promote_reviewed.py (eval-loop-automation 3.2).

Covers: verdict/reason enum validation, append-only log writes, promotion
provenance fields, the every-item-must-be-reviewed abort, the three-parameter
gate, and merge-append into an existing main dataset.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.scripts import promote_reviewed, review_log


# ── review_log: entry validation ─────────────────────────────────────


def test_reject_requires_enum_reason():
    with pytest.raises(ValueError, match="reject reason"):
        review_log.build_entry("s", "i", "reject", "not_a_reason", "", "q", 1)


def test_reject_requires_question():
    with pytest.raises(ValueError, match="question"):
        review_log.build_entry("s", "i", "reject", "too_shallow", "n", "", 1)


def test_reason_other_requires_note():
    with pytest.raises(ValueError, match="note"):
        review_log.build_entry("s", "i", "reject", "other", "", "q", 1)


def test_show_id_guard_is_machine_only():
    with pytest.raises(ValueError, match="reject reason"):
        review_log.build_entry("s", "i", "reject", "show_id_guard", "n", "q", 1)


def test_approve_entry_shape():
    e = review_log.build_entry("yi-jia-yi", "item-1", "approve", "", "", "", 2)
    assert e["verdict"] == "approve"
    assert e["round"] == 2
    assert set(e) == {"ts", "show_slug", "item_id", "verdict", "reason", "note", "question", "round"}


def test_cli_appends_jsonl(tmp_path):
    log = tmp_path / "log.jsonl"
    rc = review_log.main([
        "--show-slug", "yi-jia-yi", "--item-id", "i1", "--verdict", "approve",
        "--round", "1", "--review-log", str(log),
    ])
    rc2 = review_log.main([
        "--show-slug", "yi-jia-yi", "--item-id", "i2", "--verdict", "reject",
        "--reason", "too_shallow", "--question", "太淺的題？",
        "--round", "1", "--review-log", str(log),
    ])
    assert (rc, rc2) == (0, 0)
    lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert [l["item_id"] for l in lines] == ["i1", "i2"]


def test_cli_rejects_bad_reason(tmp_path):
    rc = review_log.main([
        "--show-slug", "s", "--item-id", "i", "--verdict", "reject",
        "--reason", "other", "--round", "1",
        "--review-log", str(tmp_path / "log.jsonl"),
    ])
    assert rc == 2


# ── promote_reviewed ─────────────────────────────────────────────────


def _staging_doc(tmp_path: Path, item_ids: list[str]) -> Path:
    doc = {
        "schema_version": "2.0",
        "show_id": "show-uuid",
        "show_slug": "yi-jia-yi",
        "items": [
            {
                "id": iid,
                "design_type": "fact",
                "question": f"題 {iid}？",
                "anchor_context": [{"chunk_id": "ep:e@1.00", "episode_title": "EP", "text": "t"}],
            }
            for iid in item_ids
        ],
    }
    path = tmp_path / "_pending_review.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _log_with(tmp_path: Path, verdict_by_id: dict[str, str], round_no: int = 1) -> Path:
    log = tmp_path / "_review_log.jsonl"
    lines = [
        json.dumps({
            "ts": "2026-07-03T00:00:00Z", "show_slug": "yi-jia-yi", "item_id": iid,
            "verdict": v, "reason": "too_shallow" if v == "reject" else "",
            "note": "", "question": "q", "round": round_no,
        }, ensure_ascii=False)
        for iid, v in verdict_by_id.items()
    ]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


def _run_promote(tmp_path, staging, log, out=None, extra=None):
    argv = [
        "--staging", str(staging), "--show-slug", "yi-jia-yi", "--round", "1",
        "--review-log", str(log),
        "--target-main", "--reviewed-by", "jacky", "--reviewed-at", "2026-07-03T10:00:00Z",
        "--out", str(out or tmp_path / "yi-jia-yi.json"),
    ]
    return promote_reviewed.main(argv + (extra or []))


def test_promotion_attaches_provenance_and_strips_anchor(tmp_path):
    staging = _staging_doc(tmp_path, ["a", "b"])
    log = _log_with(tmp_path, {"a": "approve", "b": "reject"})
    out = tmp_path / "yi-jia-yi.json"
    assert _run_promote(tmp_path, staging, log, out) == 0

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [i["id"] for i in doc["items"]] == ["a"]  # reject not promoted
    item = doc["items"][0]
    assert item["reviewed_by"] == "jacky"
    assert item["reviewed_at"] == "2026-07-03T10:00:00Z"
    assert item["review_round"] == 1
    assert item["audit_status"] == "approved"
    assert "anchor_context" not in item


def test_unreviewed_item_aborts(tmp_path):
    staging = _staging_doc(tmp_path, ["a", "b"])
    log = _log_with(tmp_path, {"a": "approve"})  # b has no verdict
    assert _run_promote(tmp_path, staging, log) == 3


def test_gate_without_metadata_exits_2(tmp_path):
    staging = _staging_doc(tmp_path, ["a"])
    log = _log_with(tmp_path, {"a": "approve"})
    rc = promote_reviewed.main([
        "--staging", str(staging), "--show-slug", "yi-jia-yi", "--round", "1",
        "--review-log", str(log), "--target-main", "--reviewed-by", "jacky",
    ])
    assert rc == 2


def test_later_verdict_overrides_earlier(tmp_path):
    staging = _staging_doc(tmp_path, ["a"])
    log = tmp_path / "_review_log.jsonl"
    entries = [
        {"ts": "t1", "show_slug": "yi-jia-yi", "item_id": "a", "verdict": "reject",
         "reason": "too_shallow", "note": "", "question": "q", "round": 1},
        {"ts": "t2", "show_slug": "yi-jia-yi", "item_id": "a", "verdict": "approve_edited",
         "reason": "", "note": "改好了", "question": "q", "round": 1},
    ]
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    out = tmp_path / "yi-jia-yi.json"
    assert _run_promote(tmp_path, staging, log, out) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [i["id"] for i in doc["items"]] == ["a"]


def test_merge_appends_to_existing_main(tmp_path):
    out = tmp_path / "yi-jia-yi.json"
    out.write_text(json.dumps({
        "schema_version": "2.0", "show_id": "show-uuid", "show_slug": "yi-jia-yi",
        "items": [{"id": "old-1", "design_type": "fact"}],
    }), encoding="utf-8")
    staging = _staging_doc(tmp_path, ["new-1"])
    log = _log_with(tmp_path, {"new-1": "approve"})
    assert _run_promote(tmp_path, staging, log, out) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [i["id"] for i in doc["items"]] == ["old-1", "new-1"]


def test_merge_id_collision_aborts(tmp_path):
    out = tmp_path / "yi-jia-yi.json"
    out.write_text(json.dumps({
        "schema_version": "2.0", "show_id": "show-uuid", "show_slug": "yi-jia-yi",
        "items": [{"id": "dup-1", "design_type": "fact"}],
    }), encoding="utf-8")
    staging = _staging_doc(tmp_path, ["dup-1"])
    log = _log_with(tmp_path, {"dup-1": "approve"})
    with pytest.raises(SystemExit, match="collision"):
        _run_promote(tmp_path, staging, log, out)


def test_wrong_show_slug_aborts(tmp_path):
    staging = _staging_doc(tmp_path, ["a"])
    log = _log_with(tmp_path, {"a": "approve"})
    rc = promote_reviewed.main([
        "--staging", str(staging), "--show-slug", "other-show", "--round", "1",
        "--review-log", str(log),
        "--target-main", "--reviewed-by", "jacky", "--reviewed-at", "t",
        "--out", str(tmp_path / "o.json"),
    ])
    assert rc == 2
