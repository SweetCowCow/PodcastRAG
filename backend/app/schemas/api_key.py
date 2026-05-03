import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


def mask_api_key(raw: str) -> str:
    """Return the trailing 4 characters preceded by a fixed bullet block.

    Empty / very short keys collapse to a constant marker so the UI never
    accidentally exposes a substantive prefix.
    """
    if not raw or len(raw) <= 4:
        return "••••"
    return f"••••{raw[-4:]}"


class ApiKeyCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1)


class ApiKeyUpdate(BaseModel):
    """PATCH payload. provider is immutable; label and api_key are optional."""

    label: str | None = Field(default=None, min_length=1, max_length=100)
    api_key: str | None = Field(default=None, min_length=1)


class ApiKeyResponse(BaseModel):
    """Outgoing shape; api_key is always masked."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    label: str
    api_key_masked: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, row) -> "ApiKeyResponse":
        return cls(
            id=row.id,
            provider=row.provider,
            label=row.label,
            api_key_masked=mask_api_key(row.api_key),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
