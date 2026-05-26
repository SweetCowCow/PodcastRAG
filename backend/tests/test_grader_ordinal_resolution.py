from backend.eval.graders.ordinal_resolution import grade

EP131 = "c1d87278-7dba-4fb1-930d-c2bd3a3461d2"
EP142 = "ep142-uuid"
EP134 = "ep134-uuid"
EP55 = "86115ef5-76f0-4606-99cc-98c2facb2439"

T1_ENUM = [
    {"episode_id": EP142, "title": "EP142", "published_at": "2026-04-22T00:00:00Z"},
    {"episode_id": EP134, "title": "EP134", "published_at": "2026-02-25T00:00:00Z"},
    {"episode_id": EP131, "title": "EP131", "published_at": "2026-01-28T00:00:00Z"},
    {"episode_id": EP55, "title": "EP55", "published_at": "2024-08-21T00:00:00Z"},
]


def _mt01_item() -> dict:
    return {
        "id": "mt01",
        "is_multi_turn": True,
        "turns": [
            {"turn": "t1", "question": "歌單有哪幾集？"},
            {
                "turn": "t2",
                "question": "第三集是什麼內容？",
                "carry_from": "t1.enumeration_episodes[2] sorted by published_at DESC",
                "ordinal_resolution_check": True,
            },
        ],
    }


def test_mt01_t2_wrong_resolution_fails():
    """Agent picks EP55 instead of EP131 → fail."""
    item = _mt01_item()
    response = {
        "tool_calls": [
            {"name": "get_episode_summary", "args": {"episode_id": EP55}}
        ]
    }
    out = grade(item, response, prior_turn_context={"enumeration_episodes": T1_ENUM})
    assert out["score"] == 0.0
    assert out["passed"] is False
    assert out["details"]["expected_episode_id"] == EP131
    assert out["details"]["actual_episode_id"] == EP55


def test_mt01_t2_correct_resolution_passes():
    item = _mt01_item()
    response = {
        "tool_calls": [
            {"name": "get_episode_summary", "args": {"episode_id": EP131}}
        ]
    }
    out = grade(item, response, prior_turn_context={"enumeration_episodes": T1_ENUM})
    assert out["score"] == 1.0
    assert out["passed"] is True


def test_single_turn_returns_none():
    item = {"id": "b15", "is_multi_turn": False, "design_type": "deep_dive"}
    assert grade(item, {"tool_calls": []}) is None


def test_multi_turn_without_ordinal_flag_returns_none():
    item = {
        "id": "mt02",
        "is_multi_turn": True,
        "turns": [
            {"turn": "t1"},
            {"turn": "t2"},  # no ordinal_resolution_check
        ],
    }
    assert grade(item, {"tool_calls": []}) is None


def test_asc_order_works():
    item = {
        "id": "mt-asc",
        "is_multi_turn": True,
        "turns": [
            {"turn": "t1"},
            {
                "turn": "t2",
                "carry_from": "t1.enumeration_episodes[0] sorted by published_at ASC",
                "ordinal_resolution_check": True,
            },
        ],
    }
    # ASC, index 0 → oldest = EP55
    response = {"tool_calls": [{"name": "get_episode_summary", "args": {"episode_id": EP55}}]}
    out = grade(item, response, prior_turn_context={"enumeration_episodes": T1_ENUM})
    assert out["passed"] is True
