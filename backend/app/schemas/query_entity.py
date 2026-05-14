"""Pydantic shape for the LLM-extracted query entities.

The LLM gets the user's question + the current datetime, returns a JSON
object matching `QueryEntities`. The JSON schema is exposed via
`QUERY_ENTITIES_JSON_SCHEMA` for OpenAI's `response_format` (structured
output).

Empty fields signal "no entity of this kind detected" — the chat path
treats an all-empty result as fail-open (no metadata filtering).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class QueryEntities(BaseModel):
    """Extracted entities for metadata-filter-aware RAG retrieval.

    All fields are optional; absence means "no constraint for this kind".
    """

    date_range: tuple[datetime, datetime] | None = Field(
        default=None,
        description=(
            "Inclusive UTC datetime range when the question references a "
            "concrete or abstract time window (e.g. '2024 那集', '去年'). "
            "Both endpoints SHALL be ISO 8601 strings; the model fills in "
            "year-boundary midnights for whole-year mentions."
        ),
    )
    guests: list[str] = Field(
        default_factory=list,
        description=(
            "Guest names mentioned in the question (e.g. '馬世芳'). "
            "Aliases SHALL NOT be normalized at this layer — the chat path "
            "decides downstream whether to fall back to fuzzy matching."
        ),
    )
    topics: list[str] = Field(
        default_factory=list,
        description=(
            "Topic keywords the question pivots on (e.g. '歌單', '高雄美食'). "
            "Empty list means no topic constraint."
        ),
    )

    @classmethod
    def empty(cls) -> "QueryEntities":
        """Return the no-constraints sentinel used by fail-open paths."""
        return cls(date_range=None, guests=[], topics=[])

    def is_empty(self) -> bool:
        return self.date_range is None and not self.guests and not self.topics


# JSON Schema (draft-2020-12) for OpenAI structured output.
# Note: response_format requires `additionalProperties: false` and an explicit
# `required` array listing every property.
QUERY_ENTITIES_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["date_range", "guests", "topics"],
    "properties": {
        "date_range": {
            "anyOf": [
                {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "string", "format": "date-time"},
                },
                {"type": "null"},
            ],
            "description": "Inclusive [start, end] ISO 8601 datetimes, or null when the question has no time reference.",
        },
        "guests": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 50},
        },
        "topics": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 50},
        },
    },
}
