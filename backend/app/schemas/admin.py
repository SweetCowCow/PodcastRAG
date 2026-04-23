from datetime import datetime

from pydantic import BaseModel

MASKED_API_KEY = "***"


class LlmConfigResponse(BaseModel):
    answer_base_url: str
    answer_api_key: str = MASKED_API_KEY
    answer_model: str
    rewrite_base_url: str
    rewrite_api_key: str = MASKED_API_KEY
    rewrite_model: str
    updated_at: datetime


class LlmConfigUpdate(BaseModel):
    answer_base_url: str | None = None
    answer_api_key: str | None = None
    answer_model: str | None = None
    rewrite_base_url: str | None = None
    rewrite_api_key: str | None = None
    rewrite_model: str | None = None
