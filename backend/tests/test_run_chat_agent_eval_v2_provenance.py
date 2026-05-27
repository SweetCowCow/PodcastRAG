"""Tests for run_chat_agent_eval_v2 baseline provenance metadata."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.scripts.run_chat_agent_eval_v2 import (
    CITATION_FIX_COMMIT,
    _build_provenance,
    _citation_fix_applied,
    _write_output,
    main,
)


def test_full_run_provenance_records_all_fields(tmp_path):
    """Scenario 1: successful baseline run records full provenance."""
    prov = _build_provenance(
        prod_commit="336c69d",
        citation_fix_confirmed=False,
        dataset_path=Path("backend/eval/datasets/extended-multi-turn-40.json"),
        dataset_schema_version_str="2.0",
        run_started_at="2026-05-27T10:00:00Z",
        run_completed_at="2026-05-27T10:42:00Z",
    )
    assert prov["backend_commit"] == "336c69d"
    assert prov["dataset_schema_version"] == "2.0"
    assert prov["dataset_path"].endswith("extended-multi-turn-40.json")
    assert prov["run_started_at"] == "2026-05-27T10:00:00Z"
    assert prov["run_completed_at"] == "2026-05-27T10:42:00Z"
    assert prov["citation_collector_fix_applied"] is True

    out = tmp_path / "baseline.json"
    _write_output(
        out,
        results=[{"item_id": "b20", "design_type": "cross_episode", "indicators": {}}],
        aggregate_report={"by_design_type": {}, "overall": {}},
        judge_model="model-x",
        judge_sha="sha-x",
        provenance=prov,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["provenance"] == prov
    assert payload["n_items"] == 1


def test_partial_run_provenance_has_real_completed_timestamp(tmp_path):
    """Scenario 2: partial run preserves provenance with real timestamp (not null)."""
    prov = _build_provenance(
        prod_commit="336c69d",
        citation_fix_confirmed=True,
        dataset_path=Path("dummy.json"),
        dataset_schema_version_str="2.0",
        run_started_at="2026-05-27T10:00:00Z",
        run_completed_at="2026-05-27T10:15:33Z",
    )
    assert prov["run_completed_at"] is not None
    assert prov["run_completed_at"] != ""
    assert prov["run_completed_at"].startswith("2026-")

    out = tmp_path / "partial.json"
    _write_output(
        out,
        results=[
            {"item_id": "b20", "design_type": "cross_episode", "indicators": {}},
            {"item_id": "b21", "design_type": "cross_episode", "indicators": {}},
        ],
        aggregate_report={"by_design_type": {}, "overall": {}},
        judge_model="m",
        judge_sha="s",
        provenance=prov,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["provenance"]["run_completed_at"] == "2026-05-27T10:15:33Z"
    assert payload["n_items"] == 2


def test_refuse_overwrite_without_force(tmp_path, monkeypatch, capsys):
    """Scenario 3: refuse to overwrite existing baseline without --force."""
    output = tmp_path / "baseline.json"
    output.write_text('{"existing": true}', encoding="utf-8")
    report = tmp_path / "report.md"
    dataset = tmp_path / "dataset.json"
    dataset.write_text('{"schema_version": "2.0", "show_id": "x", "items": []}', encoding="utf-8")
    cookie = tmp_path / "cookie.txt"
    cookie.write_text("podcastrag-api.zeabur.app\tFALSE\t/\tTRUE\t0\tcsrf_token\tabc\n", encoding="utf-8")
    me = tmp_path / "me.json"
    me.write_text('{"csrf_token": "abc"}', encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_chat_agent_eval_v2",
            "--dataset",
            str(dataset),
            "--backend",
            "http://x",
            "--session-cookie-file",
            str(cookie),
            "--me-json",
            str(me),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
    )
    rc = main()
    assert rc == 2
    captured = capsys.readouterr()
    assert "existing baseline" in captured.err
    assert "--force" in captured.err
    assert json.loads(output.read_text(encoding="utf-8")) == {"existing": True}


def test_citation_fix_applied_via_git_ancestry():
    """Direct unit test for _citation_fix_applied helper (Scenario 1 derivation)."""
    fake_ok = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    with patch("backend.scripts.run_chat_agent_eval_v2.subprocess.run", return_value=fake_ok):
        assert _citation_fix_applied("336c69d", confirm_flag=False) is True

    fake_no = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"")
    with patch("backend.scripts.run_chat_agent_eval_v2.subprocess.run", return_value=fake_no):
        assert _citation_fix_applied("oldsha1", confirm_flag=False) is False

    # confirm flag bypasses git check
    assert _citation_fix_applied(None, confirm_flag=True) is True

    # missing commit + no confirm = unknown -> False
    assert _citation_fix_applied(None, confirm_flag=False) is False


def test_citation_fix_commit_constant():
    """Sanity: the constant points to the actual fix commit referenced in spec."""
    assert CITATION_FIX_COMMIT == "287e73b"
