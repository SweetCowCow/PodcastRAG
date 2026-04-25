from pydantic import BaseModel


class SyncResponse(BaseModel):
    added: int
    updated: int
    total: int


class TranscribeLatestResponse(BaseModel):
    queued: int
    synced: SyncResponse
