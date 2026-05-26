from backend.eval.graders.chunk_recall_grouped import grade

EP = "c1d87278-7dba-4fb1-930d-c2bd3a3461d2"


def _cit(start: float, ep: str = EP) -> dict:
    return {"episode_id": ep, "start_time": start}


def test_b14_must_plus_either_full_score():
    item = {
        "id": "b14",
        "ground_truth_chunk_ids_must": [f"ep:{EP}@0.00"],
        "ground_truth_chunk_ids_either": [
            f"ep:{EP}@1790.18",
            f"ep:{EP}@1808.78",
        ],
        "ground_truth_chunk_ids_acceptable": [f"ep:{EP}@1663.58"],
    }
    resp = {"citations": [_cit(0.0), _cit(1808.78), _cit(531.12)]}
    out = grade(item, resp)
    assert out["score"] == 1.0
    assert out["passed"] is True
    assert out["details"]["either_group_hit"] is True
    assert out["details"]["either_hit_chunk"] == f"ep:{EP}@1808.78"
    assert out["details"]["acceptable_hits"] == 0


def test_must_miss_partial_score():
    item = {
        "ground_truth_chunk_ids_must": [f"ep:{EP}@0.00", f"ep:{EP}@500.00"],
    }
    resp = {"citations": [_cit(0.0)]}  # only 1 of 2 must
    out = grade(item, resp)
    assert out["score"] == 0.5
    assert out["passed"] is False


def test_either_group_any_chunk_counts():
    item = {
        "ground_truth_chunk_ids_either": [
            f"ep:{EP}@1790.18",
            f"ep:{EP}@1808.78",
        ],
    }
    # hit only the second one in the group
    resp = {"citations": [_cit(1808.78)]}
    out = grade(item, resp)
    assert out["score"] == 1.0
    assert out["passed"] is True


def test_acceptable_does_not_raise_above_one():
    item = {
        "ground_truth_chunk_ids_must": [f"ep:{EP}@0.00"],
        "ground_truth_chunk_ids_acceptable": [f"ep:{EP}@1663.58"],
    }
    resp = {"citations": [_cit(0.0), _cit(1663.58)]}
    out = grade(item, resp)
    assert out["score"] == 1.0  # not 2.0
    assert out["details"]["acceptable_hits"] == 1


def test_no_gt_returns_none():
    item = {"id": "b11"}
    assert grade(item, {"citations": []}) is None


def test_window_match_tolerates_2dec_rounding():
    item = {"ground_truth_chunk_ids_must": [f"ep:{EP}@1446.34"]}
    resp = {"citations": [_cit(1446.336)]}  # off by 0.004s, within 10s window
    out = grade(item, resp)
    assert out["score"] == 1.0
