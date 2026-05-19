"""Stable fixture data for stub tools.

UUIDs are deterministic UUIDv5 so prototype runs are reproducible across
machines. Fixture data covers the multi-turn golden set cases
(Q1 '歌單' enumeration, Q3 'EP143' pin) so stub-only tools can still
exercise state carry.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .schemas import EpisodeRef, Segment, ChunkHit


_NS = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _ep_uuid(slug: str) -> uuid.UUID:
    return uuid.uuid5(_NS, slug)


EP_GEDAN_1 = _ep_uuid("ep-gedan-1")
EP_GEDAN_2 = _ep_uuid("ep-gedan-2")
EP_GEDAN_3 = _ep_uuid("ep-gedan-3")
EP_143 = _ep_uuid("ep-143")
EP_MASHIFANG = _ep_uuid("ep-mashifang")


FIXTURE_EPISODES: dict[uuid.UUID, EpisodeRef] = {
    EP_GEDAN_1: EpisodeRef(
        episode_id=EP_GEDAN_1,
        title="2024 上半年歌單",
        published_at=datetime(2024, 7, 1, tzinfo=timezone.utc),
        guests=[],
        ai_summary="主持人選 9 首 2024 上半年印象最深的歌。",
    ),
    EP_GEDAN_2: EpisodeRef(
        episode_id=EP_GEDAN_2,
        title="2024 下半年歌單",
        published_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        guests=[],
        ai_summary="主持人選 9 首 2024 下半年印象最深的歌。",
    ),
    EP_GEDAN_3: EpisodeRef(
        episode_id=EP_GEDAN_3,
        title="2025 春季歌單",
        published_at=datetime(2025, 4, 1, tzinfo=timezone.utc),
        guests=[],
        ai_summary="春季 9 首選歌，含獨立樂團與電子。",
    ),
    EP_143: EpisodeRef(
        episode_id=EP_143,
        title="EP143：跟 Axios 創辦人聊 AI 媒體",
        published_at=datetime(2024, 11, 15, tzinfo=timezone.utc),
        guests=["Jim VandeHei"],
        ai_summary="Axios 創辦人解釋 RAG 對新聞業的影響。",
    ),
    EP_MASHIFANG: EpisodeRef(
        episode_id=EP_MASHIFANG,
        title="EP120：馬世芳聊 90 年代華語搖滾",
        published_at=datetime(2024, 9, 1, tzinfo=timezone.utc),
        guests=["馬世芳"],
        ai_summary="馬世芳回顧伍佰、張震嶽、滅火器的早期樂團史。",
    ),
}


# Map fixture ref strings → episode for find_episode_by_ref stub.
REF_LOOKUP: dict[str, uuid.UUID] = {
    "EP143": EP_143,
    "ep143": EP_143,
    "Axios 那集": EP_143,
    "歌單第一集": EP_GEDAN_1,
}


def fixture_summary(episode_id: uuid.UUID) -> str:
    ep = FIXTURE_EPISODES.get(episode_id)
    if ep and ep.ai_summary:
        return ep.ai_summary
    return f"(fixture summary for {episode_id})"


def fixture_segments(
    episode_id: uuid.UUID, topic_filter: str | None
) -> list[Segment]:
    base = [
        Segment(segment_id=1, start_sec=0.0, end_sec=120.0,
                text="(fixture seg 1)", topic_label="開場"),
        Segment(segment_id=2, start_sec=120.0, end_sec=480.0,
                text="(fixture seg 2)", topic_label="主題討論"),
        Segment(segment_id=3, start_sec=480.0, end_sec=900.0,
                text="(fixture seg 3)", topic_label="收尾"),
    ]
    if topic_filter:
        return [s for s in base if topic_filter in (s.topic_label or "")]
    return base


def fixture_chunks(
    query: str, episode_id: uuid.UUID | None = None, k: int = 5
) -> list[ChunkHit]:
    ep = episode_id or EP_143
    title = FIXTURE_EPISODES.get(ep, FIXTURE_EPISODES[EP_143]).title
    return [
        ChunkHit(
            chunk_id=uuid.uuid5(_NS, f"chunk-{query}-{i}"),
            episode_id=ep,
            episode_title=title,
            text=f"(fixture chunk {i} for query '{query}')",
            rrf_score=1.0 / (i + 1),
            pool="transcript",
        )
        for i in range(min(k, 3))
    ]


def fixture_overview() -> str:
    return (
        "(fixture show overview) 這又沒有很屌：科技 + 流行文化 podcast，"
        "兩位主持人不定期邀請來賓，每集 60-90 分鐘。"
    )
