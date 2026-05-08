"""Unit tests for topic_segmentation helpers."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from app.services import topic_segmentation as ts


@dataclass
class FakeShow:
    title: str
    segment_categories: list[dict[str, Any]]


@dataclass
class FakeSegment:
    id: uuid.UUID
    start_time: float
    end_time: float
    text: str


def test_universal_labels_count_and_content():
    assert len(ts.UNIVERSAL_LABELS) == 8
    assert "intro" in ts.UNIVERSAL_LABELS
    assert "topic_main" in ts.UNIVERSAL_LABELS
    assert "sponsor" in ts.UNIVERSAL_LABELS


def test_prompt_includes_universal_labels():
    show = FakeShow(title="台通", segment_categories=[])
    segs = [
        FakeSegment(uuid.uuid4(), 0.0, 3.0, "歡迎收聽"),
        FakeSegment(uuid.uuid4(), 3.0, 30.0, "今天主題是..."),
    ]
    sys_prompt, payload = ts.build_classification_prompt(show, segs)
    for label in ts.UNIVERSAL_LABELS:
        assert label in sys_prompt, f"universal label {label} missing"
    assert "節目專屬類別" not in sys_prompt  # no extension


def test_prompt_includes_show_extensions():
    show = FakeShow(
        title="這又沒有很屌",
        segment_categories=[
            {"name": "playlist_segment", "desc": "介紹歌曲、歌單環節"},
            {"name": "live_performance", "desc": "來賓現場演唱"},
        ],
    )
    segs = [FakeSegment(uuid.uuid4(), 0.0, 3.0, "x")]
    sys_prompt, payload = ts.build_classification_prompt(show, segs)
    assert "playlist_segment" in sys_prompt
    assert "live_performance" in sys_prompt
    assert "節目專屬類別 — 這又沒有很屌" in sys_prompt
    # extension descriptions
    assert "介紹歌曲、歌單環節" in sys_prompt


def test_prompt_user_payload_shape():
    show = FakeShow(title="x", segment_categories=[])
    sid = uuid.uuid4()
    segs = [FakeSegment(sid, 1.5, 5.5, "hello")]
    _, payload = ts.build_classification_prompt(show, segs)
    assert payload == [{"id": str(sid), "start": 1.5, "end": 5.5, "text": "hello"}]


def test_allowed_label_set_includes_extensions():
    show = FakeShow(
        title="x",
        segment_categories=[{"name": "playlist_segment", "desc": "x"}],
    )
    allowed = ts._allowed_label_set(show)
    assert "intro" in allowed
    assert "playlist_segment" in allowed
    assert "live_performance" not in allowed  # not in this show's extensions


def test_short_segment_threshold():
    assert ts.SHORT_SEGMENT_THRESHOLD == 5.0
