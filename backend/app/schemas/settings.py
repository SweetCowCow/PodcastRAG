from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AppSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    max_concurrent_transcriptions: int
    monthly_cost_cap_usd: Decimal | None


class AppSettingsUpdate(BaseModel):
    """Validation per spec: max_concurrent_transcriptions ∈ [1, 3]."""

    max_concurrent_transcriptions: int | None = Field(default=None, ge=1, le=3)
    monthly_cost_cap_usd: Decimal | None = None
