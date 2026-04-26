from pydantic import BaseModel


class ApiHealthEvent(BaseModel):
    ts_ms: int
    ok: bool
    duration_ms: int
    error_category: str | None = None
    http_status: int | None = None


class ApiEntry(BaseModel):
    name: str
    latest: ApiHealthEvent | None
    recent: list[ApiHealthEvent]
    degraded: bool


class ExternalApiStatusResponse(BaseModel):
    apis: list[ApiEntry]
