from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AppSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    max_concurrent_transcriptions: int
    monthly_cost_cap_usd: Decimal | None
    keyword_t2_collapse_threshold: int


class AppSettingsUpdate(BaseModel):
    """Validation per spec: max_concurrent_transcriptions ∈ [1, 3]."""

    max_concurrent_transcriptions: int | None = Field(default=None, ge=1, le=3)
    monthly_cost_cap_usd: Decimal | None = None
    # keyword-index-mode: T2 collapse threshold (≥1; no upper bound — a high
    # value simply never collapses T2).
    keyword_t2_collapse_threshold: int | None = Field(default=None, ge=1)
