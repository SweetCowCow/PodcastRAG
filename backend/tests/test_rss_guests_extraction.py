"""Tests for R3.3 Phase 2: extract_guests_from_title regex behaviour.

Pure-Python tests — no DB or network required.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.rss_parser import extract_guests_from_title


@pytest.mark.parametrize("title,expected", [
    # Bare Ft. variants
    ("EP100 高雄美食 Ft. 楊大正", ["楊大正"]),
    ("EP66 浪人祭 Feat. 達謙", ["達謙"]),
    ("EP110 沖咖啡 feat. TMEX", ["TMEX"]),
    ("EP142 Live 演出歌單 featuring 阿廣", ["阿廣"]),
    # Bracketed forms
    ("EP15 夜夜生宵【ft. 陳陸寬 / 索艾克】", ["陳陸寬", "索艾克"]),
    ("EP140 高雄美食第二彈【Ft. 楊大正、張凱婷】", ["楊大正", "張凱婷"]),
    # Multi-guest delimiters
    ("EP44 伴手禮 Ft. 趙翊帆, 阿凱", ["趙翊帆", "阿凱"]),
    ("EP128 平價美食對決 Ft. 阿寬，邱承漢", ["阿寬", "邱承漢"]),
    # No pattern → empty
    ("EP1 節目開張", []),
    ("EP134 主持人大改版", []),
    # Empty string
    ("", []),
    # ASCII ampersand splitter (real-world: 曼報 EP112 / SP9 等)
    ("EP112 曼報 Pro 第一屆股東會 ft. Vincent & Leslie", ["Vincent", "Leslie"]),
    ("Ft. IEObserve & 商周副總編輯吳中傑", ["IEObserve", "商周副總編輯吳中傑"]),
    # Full-width ampersand
    ("ft. 甲＆乙", ["甲", "乙"]),
])
def test_extract_guests_from_title(title, expected):
    assert extract_guests_from_title(title) == expected


def test_extract_guests_strip_whitespace():
    assert extract_guests_from_title("EP1 Ft.   阿廣   ") == ["阿廣"]


def test_extract_guests_order_preserved():
    # Multiple guests in one title should preserve appearance order
    result = extract_guests_from_title("EP50 Ft. 甲, 乙, 丙")
    assert result == ["甲", "乙", "丙"]
