"""Unit tests for show_profile.py — quota rule table, profile schema, hand-edit loading.

Per eval-loop-automation tasks 1.2: each static quota rule is exercised
individually (low-guest / low-summary / no-playlist), the emitted profile
schema matches the Implementation Contract, and a hand-edited profile
remains loadable through `load_profile` (the entry build_golden_set uses).
"""
from __future__ import annotations

import json

import pytest

from eval.scripts import show_profile
from eval.scripts.show_profile import (
    BASE_QUOTAS,
    build_profile,
    compute_en_char_ratio,
    derive_quotas,
    load_profile,
)


def make_metrics(**overrides) -> dict:
    """Rich-show metrics baseline: no rule triggers."""
    metrics = {
        "total_episodes": 172,
        "guests_coverage": 0.58,
        "playlist_titles": 26,
        "summary_done_ratio": 1.0,
        "en_char_ratio_sample": 0.05,
        "en_char_sample_n": 20,
    }
    metrics.update(overrides)
    return metrics


# ── quota rule table, one rule per test ──────────────────────────────


def test_rich_show_keeps_base_quotas():
    assert derive_quotas(make_metrics()) == BASE_QUOTAS


def test_low_guest_coverage_zeroes_guest_find_and_redistributes():
    # spec example: 壹加壹 6/261 = 0.02 → guest_find 0
    quotas = derive_quotas(make_metrics(guests_coverage=0.02))
    assert quotas["guest_find"] == 0
    freed = BASE_QUOTAS["guest_find"]
    assert quotas["fact"] == BASE_QUOTAS["fact"] + (freed - freed // 2)
    assert quotas["cross_episode"] == BASE_QUOTAS["cross_episode"] + freed // 2
    # redistribution preserves total question pressure
    assert sum(quotas.values()) == sum(BASE_QUOTAS.values())


def test_guest_coverage_at_threshold_keeps_guest_find():
    quotas = derive_quotas(make_metrics(guests_coverage=0.10))
    assert quotas["guest_find"] == BASE_QUOTAS["guest_find"]


def test_low_summary_ratio_zeroes_summary_overview():
    quotas = derive_quotas(make_metrics(summary_done_ratio=0.3))
    assert quotas["summary_overview"] == 0
    # dropped, not redistributed
    assert quotas["fact"] == BASE_QUOTAS["fact"]


def test_zero_playlist_titles_zeroes_playlist_enum():
    quotas = derive_quotas(make_metrics(playlist_titles=0))
    assert quotas["playlist_enum"] == 0


# ── profile schema completeness ──────────────────────────────────────


def test_profile_schema_matches_contract():
    profile = build_profile("some-uuid", "some-slug", make_metrics())
    assert set(show_profile.REQUIRED_PROFILE_KEYS) <= set(profile)
    assert profile["show_id"] == "some-uuid"
    assert profile["slug"] == "some-slug"
    assert profile["measured_at"]  # ISO timestamp present
    assert profile["recurring_segments"] == []  # placeholder hook, always empty here
    for key in (
        "guests_coverage",
        "playlist_titles",
        "summary_done_ratio",
        "en_char_ratio_sample",
    ):
        assert key in profile["metrics"]
    assert set(profile["quotas"]) == set(BASE_QUOTAS)


# ── hand-edited profile loads through the build_golden_set entry ─────


def test_hand_edited_profile_loads(tmp_path):
    profile = build_profile("some-uuid", "some-slug", make_metrics())
    path = tmp_path / "some-slug.json"
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["quotas"]["fact"] = 5  # human override
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")

    loaded = load_profile(path)
    assert loaded["quotas"]["fact"] == 5


def test_load_profile_rejects_missing_key(tmp_path):
    profile = build_profile("some-uuid", "some-slug", make_metrics())
    del profile["quotas"]
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="quotas"):
        load_profile(path)


def test_load_profile_rejects_unknown_quota_type(tmp_path):
    profile = build_profile("some-uuid", "some-slug", make_metrics())
    profile["quotas"]["totally_new_type"] = 3
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="totally_new_type"):
        load_profile(path)


def test_load_profile_rejects_negative_quota(tmp_path):
    profile = build_profile("some-uuid", "some-slug", make_metrics())
    profile["quotas"]["fact"] = -1
    path = tmp_path / "negative.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="fact"):
        load_profile(path)


# ── en-char ratio helper ─────────────────────────────────────────────


def test_en_char_ratio_mixed_text():
    # "hello世界" → 5 EN / 7 non-space; whitespace excluded
    assert compute_en_char_ratio(["hello 世界"]) == round(5 / 7, 4)


def test_en_char_ratio_empty():
    assert compute_en_char_ratio([]) == 0.0
