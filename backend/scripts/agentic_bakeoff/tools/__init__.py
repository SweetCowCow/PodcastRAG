"""Tool registry: framework adapters iterate this to register tools.

Each entry is a `ToolSpec` capturing the LLM-facing name, description,
input schema, async-ness, and the callable. Output schema is the
callable's return annotation.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from . import impl, schemas


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    callable: Callable[..., Any]
    is_async: bool


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="find_episode_by_ref",
        description="Resolve a textual reference (e.g. 'EP143', 'Axios 那集', '上一集') to a single episode.",
        input_model=schemas.FindEpisodeByRefInput,
        callable=impl.find_episode_by_ref,
        is_async=False,
    ),
    ToolSpec(
        name="find_episodes_by_guest",
        description="Find episodes whose guests list contains the given name.",
        input_model=schemas.FindEpisodesByGuestInput,
        callable=impl.find_episodes_by_guest,
        is_async=True,
    ),
    ToolSpec(
        name="find_episodes_by_topic",
        description="Find episodes whose title or description mentions the topic keyword.",
        input_model=schemas.FindEpisodesByTopicInput,
        callable=impl.find_episodes_by_topic,
        is_async=True,
    ),
    ToolSpec(
        name="find_episodes_by_date",
        description="Find episodes published in the inclusive date range [start, end].",
        input_model=schemas.FindEpisodesByDateInput,
        callable=impl.find_episodes_by_date,
        is_async=True,
    ),
    ToolSpec(
        name="get_episode_summary",
        description="Get the AI-generated 80-150 character summary for one episode.",
        input_model=schemas.GetEpisodeSummaryInput,
        callable=impl.get_episode_summary,
        is_async=False,
    ),
    ToolSpec(
        name="get_episode_segments",
        description="List topic-labelled segments for one episode; optional topic_filter narrows by label.",
        input_model=schemas.GetEpisodeSegmentsInput,
        callable=impl.get_episode_segments,
        is_async=False,
    ),
    ToolSpec(
        name="search_within_episode",
        description="Semantic+keyword search restricted to one episode.",
        input_model=schemas.SearchWithinEpisodeInput,
        callable=impl.search_within_episode,
        is_async=False,
    ),
    ToolSpec(
        name="search_across_episodes",
        description="Semantic+keyword search across all episodes in the current show.",
        input_model=schemas.SearchAcrossEpisodesInput,
        callable=impl.search_across_episodes,
        is_async=True,
    ),
    ToolSpec(
        name="search_in_episodes",
        description="Semantic+keyword search restricted to the given list of episode_ids.",
        input_model=schemas.SearchInEpisodesInput,
        callable=impl.search_in_episodes,
        is_async=False,
    ),
    ToolSpec(
        name="get_show_overview",
        description="Get a one-paragraph overview of the current show.",
        input_model=schemas.GetShowOverviewInput,
        callable=impl.get_show_overview,
        is_async=False,
    ),
    ToolSpec(
        name="pin_episode",
        description="Pin one episode_id as focused in L1 session state (10 min idle expiry).",
        input_model=schemas.PinEpisodeInput,
        callable=impl.pin_episode,
        is_async=False,
    ),
    ToolSpec(
        name="unpin_episode",
        description="Clear the focused_episode_id in L1 session state.",
        input_model=schemas.UnpinEpisodeInput,
        callable=impl.unpin_episode,
        is_async=False,
    ),
]


TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}


__all__ = ["TOOLS", "TOOLS_BY_NAME", "ToolSpec", "schemas", "impl"]
