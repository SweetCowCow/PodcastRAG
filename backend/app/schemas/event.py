from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CitationClickPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=64)
    position: int = Field(ge=0)


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["citation_click"]
    payload: CitationClickPayload
