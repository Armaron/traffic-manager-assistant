from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import AnalysisCategory, Priority


class ImportantEntities(BaseModel):
    geo: list[str] = Field(default_factory=list)
    traffic_source: list[str] = Field(default_factory=list)
    payment_model: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)


class AIAnalysisCreate(BaseModel):
    message_id: int
    summary: str
    request: str
    category: AnalysisCategory
    priority: Priority
    needs_reply: bool
    needs_igor: bool
    reason: str
    draft_reply: str
    important_entities: ImportantEntities | None = None
    provider: str | None = None
    model: str | None = None


class AIAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    summary: str
    request: str
    category: AnalysisCategory
    priority: Priority
    needs_reply: bool
    needs_igor: bool
    reason: str
    draft_reply: str
    important_entities: dict[str, object] | None
    provider: str | None
    model: str | None
    created_at: datetime
    updated_at: datetime
