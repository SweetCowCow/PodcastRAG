"""Shared RAG data structures.

Lowest layer of the RAG service: defines the data structures shared across
retrieval, enrichment, and generation. Imports no other ``rag_*`` submodule so
the dependency direction stays acyclic.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

__all__ = ["ChunkHit", "MetadataFilters"]


@dataclass
class MetadataFilters:
    """Episode-level hard filters extracted from the user question.

    Both fields are optional; `is_empty()` true means "no metadata filter"
    and retrieval SQL skips the WHERE clause entirely (fail-open path also
    routes through here when entity extraction yields nothing).
    """

    guests: list[str] = field(default_factory=list)
    date_range: tuple[datetime, datetime] | None = None

    def is_empty(self) -> bool:
        return not self.guests and self.date_range is None


@dataclass
class ChunkHit:
    episode_id: uuid.UUID
    episode_title: str
    start_time: float
    end_time: float
    text: str
    distance: float | None = None
    chunk_id: uuid.UUID | None = None
    source: Literal["transcript", "description", "title"] = "transcript"
    rrf_score: float = 0.0
    # R2.1 citation infra fields, populated by `enrich_hits()` after retrieval.
    # Default to empty so retrieval-only callers (eval scripts, etc.) keep
    # working without enrichment.
    before_text: str = ""
    after_text: str = ""
    highlights: str = ""
    ai_summary_excerpt: str = ""
    # R2.1 followup: full (untruncated) ai_summary used by SourceCard
    # "expand" toggle. None when the episode has no ai_summary.
    ai_summary_full: str | None = None
    # chunking-version-coexistence: which description chunking pass produced
    # this hit. 1 = legacy whole-description (default; also transcript hits).
    # 2 = pilot re-chunk (≤200 chars). Surfaced in retrieval so eval / admin
    # tooling can attribute Recall lifts to the rollout.
    chunking_version: int = 1
    chunk_index: int = 0
