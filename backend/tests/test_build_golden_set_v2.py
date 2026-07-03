"""Unit tests for anchor-first build_golden_set.py (eval-loop-automation 2.4).

Covers: anchor-first ordering (anchor exists before the question), show-id
guard auto-reject, review-grade decision matrix, negative few-shot injection
from a mocked review log, and the staging-only default (three-parameter gate).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.scripts import build_golden_set as bgs
from eval.scripts.show_profile import build_profile


def make_chunk(ep_id: str, start: float, text: str = "x" * 100) -> dict:
    return {
        "db_id": f"db-{ep_id}-{start}",
        "chunk_id": f"ep:{ep_id}@{start:.2f}",
        "text": text,
        "episode_id": ep_id,
        "episode_title": f"EP {ep_id}",
        "published_at": None,
    }


def write_profile(tmp_path: Path, quotas_override: dict) -> Path:
    metrics = {
        "total_episodes": 10,
        "guests_coverage": 0.5,
        "playlist_titles": 1,
        "summary_done_ratio": 1.0,
        "en_char_ratio_sample": 0.05,
        "en_char_sample_n": 10,
    }
    profile = build_profile("show-uuid", "test-show", metrics)
    profile["quotas"] = {k: 0 for k in profile["quotas"]}
    profile["quotas"].update(quotas_override)
    path = tmp_path / "test-show.json"
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    return path


# ── anchor-first ordering ────────────────────────────────────────────


class _StubConn:
    pass


class _StubEngine:
    def connect(self):
        conn = _StubConn()

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    async def dispose(self):
        pass


async def test_anchor_sampled_before_question_generation(tmp_path, monkeypatch):
    """The pipeline SHALL sample anchors first; the LLM only ever sees
    pre-sampled chunks and the item's GT is bound to exactly those chunks."""
    events: list[str] = []
    anchor = make_chunk("ep-aaa", 12.3)

    async def fake_fetch_show_data(conn, show_id):
        return {
            "show_id": show_id,
            "show_title": "測試節目",
            "episodes": [{"id": "ep-aaa", "title": "EP1", "duration_seconds": 100,
                          "published_at": None, "guests": [], "description": "",
                          "ai_summary": None, "ai_summary_status": "done",
                          "transcript_id": "t1"}],
        }

    async def fake_sample_anchor_group(conn, qtype, show, ep_cycle, rng):
        events.append("sample")
        return {"chunks": [anchor], "episode": show["episodes"][0]}

    def fake_call_llm(model, prompt, **kwargs):
        events.append("llm")
        return {
            "question": "迪拉在 EP1 提到的餐廳叫什麼名字？",
            "expected_answer_summary": "答案摘要",
            "expected_answer_aliases": None,
        }

    monkeypatch.setattr(bgs, "fetch_show_data", fake_fetch_show_data)
    monkeypatch.setattr(bgs, "sample_anchor_group", fake_sample_anchor_group)
    monkeypatch.setattr(bgs, "call_llm", fake_call_llm)
    import sqlalchemy.ext.asyncio as sa_asyncio
    monkeypatch.setattr(sa_asyncio, "create_async_engine", lambda url: _StubEngine())

    profile = json.loads(write_profile(tmp_path, {"fact": 1}).read_text(encoding="utf-8"))
    items, valid_eps = await bgs.generate_all(
        "postgresql+asyncpg://stub", profile, "test-model", 1, [], ""
    )

    assert events == ["sample", "llm"], "anchor sampling must precede the LLM call"
    assert len(items) == 1
    assert items[0]["ground_truth_chunk_ids_must"] == [anchor["chunk_id"]]
    assert valid_eps == {"ep-aaa"}


def test_cross_episode_must_outside_anchors_rejected():
    """LLM cannot invent GT: must_chunk_ids outside the sampled set fail."""
    anchor_ids = {"ep:aaa@1.00", "ep:bbb@2.00"}
    cand = {
        "question": "兩集裡主持人對嘻哈 battle 的看法有什麼不同？",
        "expected_answer_summary": "摘要",
        "must_chunk_ids": ["ep:aaa@1.00", "ep:zzz@9.00"],  # zzz never sampled
    }
    ok, reason = bgs.validate_candidate(cand, "cross_episode", anchor_ids)
    assert not ok
    assert "outside sampled anchors" in reason


def test_cross_episode_must_span_two_episodes():
    anchor_ids = {"ep:aaa@1.00", "ep:aaa@2.00", "ep:bbb@3.00"}
    cand = {
        "question": "主持人在多集裡怎麼談 KFC 炸雞？",
        "expected_answer_summary": "摘要",
        "must_chunk_ids": ["ep:aaa@1.00", "ep:aaa@2.00"],
    }
    ok, reason = bgs.validate_candidate(cand, "cross_episode", anchor_ids)
    assert not ok
    assert "≥2 episodes" in reason


# ── show-id guard: the only automatic rejection ──────────────────────


def _staged_item(item_id: str, ep_id: str) -> dict:
    return {
        "id": item_id,
        "design_type": "fact",
        "question": "測試題？",
        "expected_answer_summary": "摘要",
        "ground_truth_chunk_ids_must": [f"ep:{ep_id}@1.00"],
        "ground_truth_chunk_ids_acceptable": None,
        "anchor_context": [
            {"chunk_id": f"ep:{ep_id}@1.00", "episode_title": "EP", "text": "內文"}
        ],
    }


def test_show_id_guard_auto_rejects_and_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bgs, "judge_item",
        lambda model, item: {"anchor_aligned": True, "must_ok": True, "note": ""},
    )
    log_path = tmp_path / "_review_log.jsonl"
    items = [
        _staged_item("keep-01", "ep-inside"),
        _staged_item("drop-01", "ep-foreign"),
    ]
    kept = bgs.run_pre_review(
        items,
        valid_episode_ids={"ep-inside"},
        show_id="show-uuid",
        show_slug="test-show",
        round_no=1,
        judge_model="judge",
        backend_url="http://unused",
        auth_token="",
        review_log_path=log_path,
        skip_retrieval=True,
    )
    assert [i["id"] for i in kept] == ["keep-01"]
    lines = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["item_id"] == "drop-01"
    assert lines[0]["verdict"] == "reject"
    assert lines[0]["reason"] == "show_id_guard"
    assert lines[0]["round"] == 1


# ── review-grade decision matrix ─────────────────────────────────────


@pytest.mark.parametrize(
    ("qtype", "aligned", "must_ok", "rank", "expected"),
    [
        ("fact", True, True, 5, "light"),
        ("fact", True, True, 20, "light"),   # boundary: ≤20 stays light
        ("fact", False, True, 1, "heavy"),   # check 1 fail forces heavy
        ("fact", True, False, 1, "heavy"),   # check 2 fail forces heavy
        ("fact", True, True, 21, "heavy"),   # retrieval grades (not rejects)
        ("fact", True, True, None, "heavy"), # miss / skipped → heavy
        ("negative", True, True, None, "heavy"),  # negative always heavy
    ],
)
def test_review_grade_matrix(qtype, aligned, must_ok, rank, expected):
    assert bgs.compute_review_grade(qtype, aligned, must_ok, rank) == expected


def test_skip_retrieval_signal_forces_heavy(tmp_path, monkeypatch):
    """--skip-retrieval-signal → rank stays None → every item heavy."""
    monkeypatch.setattr(
        bgs, "judge_item",
        lambda model, item: {"anchor_aligned": True, "must_ok": True, "note": ""},
    )
    called = []
    monkeypatch.setattr(
        bgs, "retrieval_rank",
        lambda *a, **k: called.append(1) or 1,
    )
    kept = bgs.run_pre_review(
        [_staged_item("x-01", "ep-inside")],
        valid_episode_ids={"ep-inside"},
        show_id="show-uuid",
        show_slug="test-show",
        round_no=1,
        judge_model="judge",
        backend_url="http://unused",
        auth_token="",
        review_log_path=tmp_path / "log.jsonl",
        skip_retrieval=True,
    )
    assert not called, "retrieval must not be hit when skipped"
    assert kept[0]["pre_review"]["retrieval_rank"] is None
    assert kept[0]["pre_review"]["review_grade"] == "heavy"


# ── negative few-shot injection (mocked review log) ──────────────────


def _log_line(item_id: str, verdict: str, reason: str = "too_shallow", show: str = "test-show") -> str:
    return json.dumps({
        "ts": "2026-07-03T00:00:00Z", "show_slug": show, "item_id": item_id,
        "verdict": verdict, "reason": reason, "note": "n",
        "question": f"被打槍的題目 {item_id}？", "round": 1,
    }, ensure_ascii=False)


def test_negative_fewshot_from_mock_log(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text(
        "\n".join([
            _log_line("a-01", "reject", "too_shallow"),
            _log_line("a-02", "reject", "too_shallow"),
            _log_line("a-03", "reject", "anchor_mismatch"),
            _log_line("a-04", "approve"),
        ]) + "\n",
        encoding="utf-8",
    )
    block = bgs.build_negative_fewshot(log, "test-show")
    assert "too_shallow×2" in block
    assert "被打槍的題目 a-01？" in block
    assert "a-04" not in block  # approvals are not negative examples


def test_negative_fewshot_capped_at_five(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text(
        "\n".join(_log_line(f"a-{i:02d}", "reject") for i in range(8)) + "\n",
        encoding="utf-8",
    )
    block = bgs.build_negative_fewshot(log, "test-show", cap=5)
    assert block.count("被打槍的題目") == 5


def test_negative_fewshot_empty_without_rejects(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text(_log_line("a-01", "approve") + "\n", encoding="utf-8")
    assert bgs.build_negative_fewshot(log, "test-show") == ""
    assert bgs.build_negative_fewshot(tmp_path / "missing.jsonl", "test-show") == ""


# ── staging-only default: three-parameter gate unchanged ─────────────


def test_target_main_without_review_metadata_exits_2(tmp_path):
    profile_path = write_profile(tmp_path, {"fact": 1})
    rc = bgs.main(["--profile", str(profile_path), "--target-main"])
    assert rc == 2


def test_target_main_with_partial_metadata_exits_2(tmp_path):
    profile_path = write_profile(tmp_path, {"fact": 1})
    rc = bgs.main([
        "--profile", str(profile_path), "--target-main", "--reviewed-by", "jacky",
    ])
    assert rc == 2


def test_judge_model_equal_to_generation_model_exits_2(tmp_path):
    profile_path = write_profile(tmp_path, {"fact": 1})
    rc = bgs.main([
        "--profile", str(profile_path),
        "--model", "same-model", "--judge-model", "same-model",
    ])
    assert rc == 2
