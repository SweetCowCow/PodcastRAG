import uuid
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CitationClickPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=64)
    position: int = Field(ge=0)


class SearchExecutedPayload(BaseModel):
    """landing-and-mode-orchestration-redesign: emitted after a successful
    Semantic or Chat query so trending-queries can rank popular questions
    per show.
    """

    model_config = ConfigDict(extra="forbid")

    show_id: uuid.UUID
    query_text: str = Field(min_length=1, max_length=500)
    mode: Literal["semantic", "chat"]


class EventCreate(BaseModel):
    """Discriminated by `event_type`: validates `payload` against the
    matching schema. Unknown event_type values are rejected by the
    `Literal` constraint with 422.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["citation_click", "search_executed"]
    payload: Union[CitationClickPayload, SearchExecutedPayload]

    @model_validator(mode="after")
    def _check_payload_matches_type(self) -> "EventCreate":
        if self.event_type == "citation_click" and not isinstance(
            self.payload, CitationClickPayload
        ):
            raise ValueError("payload schema does not match citation_click")
        if self.event_type == "search_executed" and not isinstance(
            self.payload, SearchExecutedPayload
        ):
            raise ValueError("payload schema does not match search_executed")
        return self
