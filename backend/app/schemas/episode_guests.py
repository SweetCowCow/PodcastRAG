"""Pydantic schemas for the admin Episode Guests endpoints.

The episode.guests JSONB column stores a list of guest names. Admin can
view via GET, replace via PUT (full overwrite, not merge), and list a
whole show's guest assignments via the list endpoint.

Validation rules (enforced at schema level):
- Each guest name SHALL be a non-empty string after .strip()
- Each guest name SHALL be ≤ 100 characters after .strip()
- The list SHALL contain ≤ 20 entries (enough for any plausible co-host
  arrangement; rejects accidental "list of every name in transcript")
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EpisodeGuestsOut(BaseModel):
    """Single-episode guest snapshot used by GET endpoints."""

    model_config = ConfigDict(from_attributes=True)

    # Validation alias 'id' lets us load straight from the ORM (Episode.id);
    # the serialized JSON key is the field name 'episode_id'.
    episode_id: uuid.UUID = Field(validation_alias="id")
    title: str
    published_at: datetime | None
    guests: list[str]


class EpisodeGuestsUpdate(BaseModel):
    """Body for PUT /admin/episodes/{id}/guests — replaces the list."""

    guests: list[str] = Field(..., min_length=0, max_length=20)

    @field_validator("guests", mode="before")
    @classmethod
    def _strip_and_validate(cls, v):
        if not isinstance(v, list):
            raise ValueError("guests must be a list of strings")
        out: list[str] = []
        for item in v:
            if not isinstance(item, str):
                raise ValueError("each guest entry must be a string")
            stripped = item.strip()
            if not stripped:
                raise ValueError("guest entries MUST NOT be empty after strip")
            if len(stripped) > 100:
                raise ValueError(f"guest name too long (>100 chars): {stripped[:30]}…")
            out.append(stripped)
        return out
