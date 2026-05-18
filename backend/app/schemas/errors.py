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
    NOT_AUTHENTICATED = "not_authenticated"
    FORBIDDEN = "forbidden"
    CSRF_TOKEN_MISSING = "csrf_token_missing"
    CSRF_TOKEN_INVALID = "csrf_token_invalid"
    ORIGIN_MISSING = "origin_missing"
    ORIGIN_FORBIDDEN = "origin_forbidden"
    INVALID_OAUTH_STATE = "invalid_oauth_state"
    ACCOUNT_DISABLED = "account_disabled"
    QUOTA_EXHAUSTED = "quota_exhausted"
    QUOTA_REQUEST_PENDING = "quota_request_pending"
    QUOTA_REQUEST_ALREADY_PROCESSED = "already_processed"
    IP_RATE_LIMITED = "ip_rate_limited"
    # disabled-user-appeal-flow
    INVALID_REASON = "invalid_reason"
    RATE_LIMITED = "rate_limited"


class ErrorResponse(BaseModel):
    error_code: str
    provider: str | None = None
    detail: str
