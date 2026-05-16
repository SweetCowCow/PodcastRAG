"""r3-3-chat-enum-grounding: grounding block renderer tests.

`format_enumeration_block` in `app.services.rag` shapes the system-prompt
block that prepends the answer LLM call when the chat path detected an
enumeration query. These tests cover the four header variants the spec
calls out (normal / truncated >30 / guest-only fallback / empty result).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.schemas.query import EpisodeRef
from app.schemas.query_entity import QueryEntities
from app.services.rag import (
    ENUMERATION_BLOCK_MAX_LIST_ROWS,
    format_enumeration_block,
)


def _ref(title: str, *, year: int = 2024, guests: list[str] | None = None) -> EpisodeRef:
    return EpisodeRef(
        episode_id=uuid.uuid4(),
        title=title,
        published_at=datetime(year, 4, 29, tzinfo=timezone.utc),
        guests=guests or [],
        ai_summary=None,
    )


# ---------------------------------------------------------------------------
# Normal (1-30 episodes, no fallback)
# ---------------------------------------------------------------------------

def test_grounding_block_structured_format_two_episodes():
    """Spec example shape: header + intro sentence + numbered list with
    title, date, guests."""
    eps = [
        _ref("EP143「從餐廳請客到自家廚房」", guests=["馬世芳"]),
        _ref("EP140「高雄美食第二彈」"),
    ]
    block = format_enumeration_block(
        episodes=eps, total=2, fallback_marker="none",
        entities=QueryEntities(guests=["馬世芳"]),
    )
    assert "## 相關集數清單（共 2 集）" in block
    assert "這個問題的搜尋結果鎖定以下集數" in block
    assert "1. EP143「從餐廳請客到自家廚房」 (2024-04-29, ft. 馬世芳)" in block
    assert "2. EP140「高雄美食第二彈」 (2024-04-29)" in block


def test_grounding_block_no_guests_no_ft_suffix():
    """Episodes without guests should NOT show an empty 'ft.' segment."""
    eps = [_ref("EP140「高雄美食」")]
    block = format_enumeration_block(
        episodes=eps, total=1, fallback_marker="none",
        entities=QueryEntities(topics=["高雄"]),
    )
    assert "ft." not in block


def test_grounding_block_missing_publish_date_shows_placeholder():
    eps = [EpisodeRef(
        episode_id=uuid.uuid4(), title="無日期集數",
        published_at=None, guests=[], ai_summary=None,
    )]
    block = format_enumeration_block(
        episodes=eps, total=1, fallback_marker="none",
        entities=QueryEntities.empty(),
    )
    assert "未知日期" in block


# ---------------------------------------------------------------------------
# Truncation at 30 rows
# ---------------------------------------------------------------------------

def test_grounding_block_truncates_at_30_episodes():
    """Block lists only the first 30 episodes; header advertises full total."""
    eps = [_ref(f"EP{i:03d}") for i in range(50)]
    block = format_enumeration_block(
        episodes=eps, total=50, fallback_marker="none",
        entities=QueryEntities(topics=["test"]),
    )
    assert f"共 50 集，以下列出最新 {ENUMERATION_BLOCK_MAX_LIST_ROWS} 集" in block
    # The 30th episode (1-indexed) appears
    assert f"{ENUMERATION_BLOCK_MAX_LIST_ROWS}. EP{ENUMERATION_BLOCK_MAX_LIST_ROWS - 1:03d}" in block
    # The 31st episode does NOT appear
    assert f"{ENUMERATION_BLOCK_MAX_LIST_ROWS + 1}. EP{ENUMERATION_BLOCK_MAX_LIST_ROWS:03d}" not in block


def test_grounding_block_exactly_30_episodes_no_truncation_notice():
    """Header should NOT say '以下列出最新 30 集' when total === 30 (no truncation)."""
    eps = [_ref(f"EP{i:03d}") for i in range(ENUMERATION_BLOCK_MAX_LIST_ROWS)]
    block = format_enumeration_block(
        episodes=eps, total=ENUMERATION_BLOCK_MAX_LIST_ROWS, fallback_marker="none",
        entities=QueryEntities(topics=["test"]),
    )
    assert "以下列出最新" not in block
    assert f"## 相關集數清單（共 {ENUMERATION_BLOCK_MAX_LIST_ROWS} 集）" in block


# ---------------------------------------------------------------------------
# Guest-only fallback header
# ---------------------------------------------------------------------------

def test_grounding_block_guest_only_fallback_with_named_guest():
    """fallback_marker='guest_only' must surface the guest name from
    entities so the LLM has the exact noun to echo back in the answer."""
    eps = [_ref("EP143", guests=["馬世芳"])]
    block = format_enumeration_block(
        episodes=eps, total=1, fallback_marker="guest_only",
        entities=QueryEntities(guests=["馬世芳"], topics=["烤肉"]),
    )
    assert "⚠ 沒有完全相符的集數" in block
    assert "「馬世芳」" in block
    assert "全部上過的集數（共 1 集）" in block


def test_grounding_block_guest_only_fallback_with_no_guest_in_entities():
    """Defensive: fallback_marker='guest_only' but entities.guests
    empty — should still render a sensible header rather than crashing."""
    eps = [_ref("EP1")]
    block = format_enumeration_block(
        episodes=eps, total=1, fallback_marker="guest_only",
        entities=QueryEntities.empty(),
    )
    assert "⚠ 沒有完全相符的集數" in block


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------

def test_grounding_block_empty_result_uses_no_match_header():
    """0-episode case: header is the '沒有找到相符的集數' notice. The block
    still ships (LLM needs to see that the filter ran, not no context at all)."""
    block = format_enumeration_block(
        episodes=[], total=0, fallback_marker="none",
        entities=QueryEntities(guests=["林志炫"]),
    )
    assert "## 沒有找到相符的集數" in block
    assert "明確說明沒有找到" in block
