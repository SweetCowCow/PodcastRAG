from backend.eval.runner_v2_aggregate import aggregate, dataset_schema_version, render_markdown


def _item(item_id, dt, indicators):
    return {"item_id": item_id, "design_type": dt, "indicators": indicators}


def _ind(score, passed):
    return {"score": score, "passed": passed, "details": {}}


def test_aggregate_groups_by_design_type():
    results = [
        _item("b15", "deep_dive", {"recall@k": _ind(1.0, True)}),
        _item("b14", "deep_dive", {"recall@k": _ind(0.67, False)}),
        _item("b11", "date_find", {"count_consistency": _ind(0.0, False)}),
    ]
    agg = aggregate(results)
    assert agg["by_design_type"]["deep_dive"]["n_items"] == 2
    assert agg["by_design_type"]["date_find"]["n_items"] == 1
    dd_recall = agg["by_design_type"]["deep_dive"]["indicators"]["recall@k"]
    assert dd_recall["n_scored"] == 2
    assert abs(dd_recall["mean"] - 0.835) < 0.001


def test_overall_by_indicator_does_not_average_across_indicators():
    results = [
        _item("b15", "deep_dive", {"recall@k": _ind(1.0, True)}),
        _item("b11", "date_find", {"count_consistency": _ind(0.0, False)}),
    ]
    agg = aggregate(results)
    overall = agg["overall"]["by_indicator"]
    assert overall["recall@k"]["n_scored"] == 1
    assert overall["count_consistency"]["n_scored"] == 1
    # No single 'overall_mean' key spanning indicators
    assert "overall_mean" not in agg["overall"]


def test_inapplicable_indicator_skipped():
    results = [
        _item("b15", "deep_dive", {"recall@k": _ind(1.0, True), "ordinal_resolution": None}),
    ]
    agg = aggregate(results)
    dd = agg["by_design_type"]["deep_dive"]["indicators"]
    assert "recall@k" in dd
    assert "ordinal_resolution" not in dd


def test_markdown_render_separates_subgroups():
    results = [
        _item("b15", "deep_dive", {"recall@k": _ind(1.0, True)}),
        _item("b11", "date_find", {"count_consistency": _ind(0.0, False)}),
    ]
    md = render_markdown(aggregate(results), judge_prompt_sha256="a" * 64)
    assert "## deep_dive (n=1)" in md
    assert "## date_find (n=1)" in md
    assert "Summary by indicator" in md
    assert "judge_prompt_sha256: " + "a" * 64 in md


def test_schema_version_dispatch():
    assert dataset_schema_version({"schema_version": "2.0"}) == "2.0"
    assert dataset_schema_version({"version": 1}) == "v1"
