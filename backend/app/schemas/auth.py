from pydantic import BaseModel


class LogoutResponse(BaseModel):
    ok: bool = True
