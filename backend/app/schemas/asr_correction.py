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


class AsrCandidateApprove(BaseModel):
    """Optional approve payload (EQ2c F3, EQ2e F-approve). When `correct` is
    given, the rule's correct-form is overwritten before approving so an admin
    can fix a near-miss at approval time. Omitted → keep the existing value.

    `apply_to_existing` (EQ2e): when true, after approval the rule is also
    applied to existing episodes via a background job whose `task_id` is
    returned; when false (default) approval only sets the rule approved+enabled.
    """

    correct: str | None = Field(default=None, max_length=200)
    apply_to_existing: bool = False


class AsrCorrectionResponse(BaseModel):
    id: uuid.UUID
    wrong: str
    correct: str
    scope: str
    show_id: uuid.UUID | None = None
    enabled: bool
    source: str
    status: str
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by_user_id: uuid.UUID | None = None
    # EQ2e F-approve: set only when approve was called with apply_to_existing=true
    # (the enqueued rule-application Celery task id). None on every other path.
    task_id: str | None = None


class DetectExistingRequest(BaseModel):
    """EQ2e F6: trigger homophone detection over a show's existing episodes.
    The UI calls dry_run=true first (cost estimate), then confirms with false."""

    show_id: uuid.UUID
    dry_run: bool = True


class DetectExistingResponse(BaseModel):
    """dry_run=true → cost estimate (no LLM call, no writes);
    dry_run=false → the enqueued detection task id."""

    dry_run: bool
    episode_count: int = 0
    estimated_input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    missing_transcript_ids: list[str] = []
    task_id: str | None = None


class BackfillStatusResponse(BaseModel):
    """EQ2e F8 (design D3): the FIXED status shape every job state maps onto —
    never the raw Celery state. Covers detection and apply jobs alike."""

    state: str  # PENDING | PROGRESS | SUCCESS | FAILURE | REVOKED | UNKNOWN
    current: int = 0
    total: int = 0
    phase: str | None = None
    failed_chunk_ids: list[str] = []
    message: str = ""


class BackfillCancelResponse(BaseModel):
    task_id: str
    revoked: bool = True


class BatchRestoreRequest(BaseModel):
    """EQ2e F8 batch restore. D-B coarse scope (no task→episodes ledger exists):
    revert every episode that still carries a snapshot. `show_id` narrows to one
    show; omitted reverts all snapshotted episodes across every show."""

    show_id: uuid.UUID | None = None


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
