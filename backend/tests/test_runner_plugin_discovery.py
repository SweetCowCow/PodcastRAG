"""Verify plugin discovery picks up all graders and ignores underscore modules."""
import importlib
import sys
from pathlib import Path

from backend.eval.graders.loader import discover_graders, run_all


def test_discovers_four_default_graders():
    found = discover_graders()
    assert "count_consistency" in found
    assert "chunk_recall_grouped" in found
    assert "ordinal_resolution" in found
    assert "answer_contradict_check" in found


def test_skips_underscore_and_loader():
    found = discover_graders()
    for name in found:
        assert not name.startswith("_")
        assert name != "loader"


def test_dummy_grader_picked_up_after_drop_in(tmp_path, monkeypatch):
    """Drop a new module into graders dir, force re-import, verify auto-pickup."""
    graders_dir = Path("backend/eval/graders")
    dummy = graders_dir / "zz_dummy_grader.py"
    dummy.write_text(
        "def grade(item, agent_response):\n"
        "    return {'score': 0.5, 'passed': False, 'details': {'dummy': True}}\n",
        encoding="utf-8",
    )
    try:
        # Force reload package + new module
        mod_name = "backend.eval.graders.zz_dummy_grader"
        sys.modules.pop(mod_name, None)
        sys.modules.pop("backend.eval.graders", None)
        importlib.invalidate_caches()
        found = discover_graders()
        assert "zz_dummy_grader" in found, f"loader did not pick up new module; saw: {list(found)}"
    finally:
        dummy.unlink(missing_ok=True)
        for mn in list(sys.modules):
            if mn.endswith("zz_dummy_grader"):
                sys.modules.pop(mn, None)


def test_run_all_returns_dict_keyed_by_grader_name():
    item = {"id": "b11", "expected_count": 26}
    resp = {"answer": "共 26 集", "enumeration_total": 26, "citations": []}
    results = run_all(item, resp)
    assert "count_consistency" in results
    assert results["count_consistency"]["passed"] is True
    # Graders that don't apply to b11 should return None
    assert results.get("chunk_recall_grouped") is None
    assert results.get("ordinal_resolution") is None
