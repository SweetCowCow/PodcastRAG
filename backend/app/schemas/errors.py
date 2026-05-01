"""Unified error response schema for all HTTP error responses."""

from pydantic import BaseModel


class ErrorCode:
    LLM_QUOTA_EXCEEDED = "llm_quota_exceeded"
    LLM_RATE_LIMITED = "llm_rate_limited"
    LLM_AUTH_FAILED = "llm_auth_failed"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_NOT_CONFIGURED = "llm_not_configured"
    RSS_TIMEOUT = "rss_timeout"
    RSS_INVALID = "rss_invalid"
    SHOW_DUPLICATE_RSS = "show_duplicate_rss"
    INTERNAL_ERROR = "internal_error"


class ErrorResponse(BaseModel):
    error_code: str
    provider: str | None = None
    detail: str
