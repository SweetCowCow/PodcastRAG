import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AsrCorrectionCreate(BaseModel):
    wrong: str = Field(min_length=1, max_length=200)
    correct: str = Field(max_length=200)
    scope: Literal["global", "show"] = "show"
    show_id: uuid.UUID | None = None
    note: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _check_scope_show_id(self) -> "AsrCorrectionCreate":
        if self.scope == "show" and self.show_id is None:
            raise ValueError("show_id is required when scope is 'show'")
        if self.scope == "global" and self.show_id is not None:
            raise ValueError("show_id must be null when scope is 'global'")
        return self


class AsrCorrectionPatch(BaseModel):
    """Partial edit. Scope/wrong/show_id are immutable here — delete + recreate
    to change a rule's identity; this keeps the unique constraint simple."""

    correct: str | None = Field(default=None, max_length=200)
    note: str | None = None
    enabled: bool | None = None


class AsrCorrectionResponse(BaseModel):
    id: uuid.UUID
    wrong: str
    correct: str
    scope: str
    show_id: uuid.UUID | None = None
    enabled: bool
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by_user_id: uuid.UUID | None = None


class BackfillRequest(BaseModel):
    show_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    # default to a safe preview; the UI calls dry_run first, then confirms.
    dry_run: bool = True


class BackfillResponse(BaseModel):
    dry_run: bool
    affected_transcripts: int = 0
    affected_segments: int = 0
    affected_chunks: int = 0
    estimated_cost_usd: float = 0.0
    failed_chunk_ids: list[str] = []
    # set only when dry_run is false (the enqueued Celery task id)
    task_id: str | None = None


class MatchCountResponse(BaseModel):
    match_count: int
