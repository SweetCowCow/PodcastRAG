from backend.eval.graders.answer_contradict_check import grade


def test_b14_contradict_fails():
    item = {
        "id": "b14",
        "expected_must_contradict_check": "answer 不得出現『推薦振奮歌』",
    }
    resp = {
        "_judge_verdict": {
            "answer_contradict_check": {
                "passed": False,
                "rationale": "agent 直接寫『推薦振奮人心的歌』",
            }
        }
    }
    out = grade(item, resp)
    assert out["passed"] is False
    assert out["score"] == 0.0
    assert "推薦振奮" in out["details"]["judge_rationale"]


def test_no_directive_returns_none():
    item = {"id": "b27"}  # no expected_must_contradict_check
    resp = {"_judge_verdict": {"answer_contradict_check": None}}
    assert grade(item, resp) is None


def test_clean_pass():
    item = {"id": "b14", "expected_must_contradict_check": "不得提冠軍"}
    resp = {
        "_judge_verdict": {
            "answer_contradict_check": {"passed": True, "rationale": "未提冠軍"}
        }
    }
    out = grade(item, resp)
    assert out["passed"] is True
    assert out["score"] == 1.0


def test_judge_error_propagates():
    item = {"id": "b14", "expected_must_contradict_check": "X"}
    resp = {
        "_judge_verdict": {
            "answer_contradict_check": {
                "passed": False,
                "rationale": "error: timeout",
                "_error": True,
            }
        }
    }
    out = grade(item, resp)
    assert out["score"] is None
    assert "timeout" in out["details"]["error"]
