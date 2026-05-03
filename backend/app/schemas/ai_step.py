import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class AiStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_key: str
    step_type: str
    base_url: str | None
    model: str | None
    api_key_id: uuid.UUID | None
    extra_config: dict
    updated_at: datetime


# ── Update payloads (typed by step_type, validated server-side) ──


class _ChatExtraConfig(BaseModel):
    """No required fields for chat steps today; reserved for future params."""

    model_config = ConfigDict(extra="allow")


class ChatStepUpdate(BaseModel):
    step_type: Literal["chat"] = "chat"
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key_id: uuid.UUID
    extra_config: _ChatExtraConfig = Field(default_factory=_ChatExtraConfig)


class _EmbeddingExtraConfig(BaseModel):
    model_config = ConfigDict(extra="allow")


class EmbeddingStepUpdate(BaseModel):
    """Embedding endpoint. Backend additionally enforces api_key.provider == 'openai'."""

    step_type: Literal["embedding"] = "embedding"
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key_id: uuid.UUID
    extra_config: _EmbeddingExtraConfig = Field(default_factory=_EmbeddingExtraConfig)


class _WhisperApiExtra(BaseModel):
    provider: Literal["openai"]


class WhisperApiStepUpdate(BaseModel):
    """OpenAI Whisper API variant: uses base_url + api_key + model + extra.provider='openai'."""

    step_type: Literal["whisper"] = "whisper"
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key_id: uuid.UUID
    extra_config: _WhisperApiExtra


class _WhisperLocalExtra(BaseModel):
    provider: Literal["faster-whisper"]
    model_dir: str = Field(min_length=1)


class WhisperLocalStepUpdate(BaseModel):
    """faster-whisper local variant: no api_key / base_url; model_dir lives in extra."""

    step_type: Literal["whisper"] = "whisper"
    base_url: None = None
    model: str = Field(min_length=1, max_length=200)
    api_key_id: None = None
    extra_config: _WhisperLocalExtra


# Discriminated union: API layer picks the right variant by inspecting
# step_type + extra_config.provider. The router resolves the union manually
# (Pydantic discriminator on nested field is awkward), validating with the
# matching model based on the existing row's step_key.
WhisperStepUpdate = WhisperApiStepUpdate | WhisperLocalStepUpdate
AnyStepUpdate = Annotated[
    ChatStepUpdate | EmbeddingStepUpdate | WhisperApiStepUpdate | WhisperLocalStepUpdate,
    Field(discriminator=None),
]
