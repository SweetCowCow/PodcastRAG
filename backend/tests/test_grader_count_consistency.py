from backend.eval.graders.count_consistency import grade


def test_b11_off_by_one_fails():
    item = {"id": "b11", "expected_count": 26}
    resp = {"answer": "共發表了 27 集節目", "enumeration_total": 26}
    out = grade(item, resp)
    assert out["passed"] is False
    assert out["score"] == 0.0
    assert out["details"]["detected_count"] == 27


def test_no_count_pattern_passes_graceful():
    item = {"id": "b11", "expected_count": 26}
    resp = {"answer": "節目談了一些有趣的主題", "enumeration_total": 26}
    out = grade(item, resp)
    assert out["passed"] is True
    assert out["score"] == 1.0
    assert out["details"]["detected_count"] is None


def test_missing_expected_count_returns_none():
    item = {"id": "b15", "design_type": "deep_dive"}
    resp = {"answer": "any text"}
    assert grade(item, resp) is None


def test_共_prefix_match_passes():
    item = {"id": "b11", "expected_count": 26}
    resp = {"answer": "1-6 月共 26 集", "enumeration_total": 26}
    out = grade(item, resp)
    assert out["passed"] is True
    assert out["details"]["detected_count"] == 26


def test_multi_turn_picks_first_turn_count():
    item = {
        "id": "mt01",
        "is_multi_turn": True,
        "turns": [{"turn": "t1", "expected_count": 29}, {"turn": "t2"}],
    }
    resp = {"answer": "共有 30 集", "enumeration_total": 29}
    out = grade(item, resp)
    assert out["passed"] is False
    assert out["details"]["detected_count"] == 30
