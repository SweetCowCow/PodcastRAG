import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx


class RssParseError(Exception):
    pass


@dataclass
class ParsedShow:
    title: str
    description: str | None
    image_url: str | None
    language: str | None


@dataclass
class ParsedEpisode:
    title: str
    description: str | None
    audio_url: str
    duration_seconds: float | None
    published_at: datetime | None
    guid: str
    guests: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.guests is None:
            self.guests = []


# R3.3: extract guest names from episode titles.
# Covers Ft./Feat./feat./featuring + 【ft.xxx】 bracketed forms, case-insensitive.
# Pattern captures everything from the prefix to a closing delimiter (】 or
# end-of-title), then post-processing splits multi-guest cases on / 、 , ，
GUESTS_REGEX = re.compile(
    r"(?:【\s*)?(?:Ft\.|Feat\.|feat\.|featuring)\s*([^】\n]+?)(?:\s*】|$)",
    re.IGNORECASE,
)
_GUESTS_SPLIT_RE = re.compile(r"[/、,，]")


def extract_guests_from_title(title: str) -> list[str]:
    """Return ordered, de-duplicated guest names parsed from an episode title.

    Returns [] when no ft./feat. pattern is present. Splits multi-guest matches
    on /、,， delimiters and strips whitespace. Order follows first-occurrence.

    Known limitation: a title that repeats the Ft./Feat. prefix mid-string
    (e.g. "Ft. 甲 Feat. 乙") is captured as a single span "甲 Feat. 乙" up to
    end-of-string. This is acceptable because real RSS titles do not use two
    feat-prefixes for the same episode; admin can correct via the UI in Phase 5.
    """
    if not title:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in GUESTS_REGEX.findall(title):
        for piece in _GUESTS_SPLIT_RE.split(raw):
            name = piece.strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


@dataclass
class ParsedFeed:
    show: ParsedShow
    episodes: list[ParsedEpisode]


async def fetch_and_parse(url: str, max_episodes: int | None = None) -> ParsedFeed:
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise RssParseError(f"無法下載 RSS Feed: {exc}") from exc

    if response.status_code != 200:
        raise RssParseError(f"RSS Feed 回應 HTTP {response.status_code}")

    parsed = await asyncio.to_thread(feedparser.parse, response.content)

    if parsed.bozo and not parsed.entries:
        reason = getattr(parsed, "bozo_exception", "格式錯誤")
        raise RssParseError(f"RSS Feed 解析失敗: {reason}")

    if not getattr(parsed, "feed", None) or not parsed.feed.get("title"):
        raise RssParseError("RSS Feed 缺少 channel 或 title 節點")

    show = _parse_show(parsed.feed)
    entries = parsed.entries if max_episodes is None else parsed.entries[:max_episodes]
    episodes = [_parse_episode(entry) for entry in entries]
    episodes = [ep for ep in episodes if ep is not None]

    return ParsedFeed(show=show, episodes=episodes)


def _parse_show(feed: dict) -> ParsedShow:
    image_url = None
    if feed.get("image") and feed["image"].get("href"):
        image_url = feed["image"]["href"]
    elif feed.get("itunes_image"):
        image_url = feed["itunes_image"].get("href")

    return ParsedShow(
        title=feed.get("title", "").strip(),
        description=feed.get("subtitle") or feed.get("summary") or None,
        image_url=image_url,
        language=feed.get("language"),
    )


def _parse_episode(entry: dict) -> ParsedEpisode | None:
    audio_url = None
    for enclosure in entry.get("enclosures", []) or []:
        if enclosure.get("type", "").startswith("audio") or enclosure.get("url"):
            audio_url = enclosure.get("url") or enclosure.get("href")
            if audio_url:
                break

    if not audio_url:
        return None

    guid = entry.get("id") or entry.get("guid") or audio_url

    published_at = None
    if entry.get("published_parsed"):
        published_at = datetime(
            *entry.published_parsed[:6], tzinfo=timezone.utc
        )

    duration_seconds = _parse_duration(entry.get("itunes_duration"))
    title = entry.get("title", "").strip() or "(untitled)"

    return ParsedEpisode(
        title=title,
        description=entry.get("summary") or entry.get("subtitle") or None,
        audio_url=audio_url,
        duration_seconds=duration_seconds,
        published_at=published_at,
        guid=guid,
        guests=extract_guests_from_title(title),
    )


def _parse_duration(value: str | None) -> float | None:
    if not value:
        return None
    value = str(value).strip()
    if value.isdigit():
        return float(value)
    match = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$", value)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        return float(hours * 3600 + minutes * 60 + seconds)
    try:
        return float(value)
    except ValueError:
        return None
