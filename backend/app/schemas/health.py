from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    typex_mode: str
    ai_provider: str
    app_env: str
