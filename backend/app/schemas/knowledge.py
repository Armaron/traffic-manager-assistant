from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KnowledgeEntryCreate(BaseModel):
    title: str
    category: str
    content: str
    company_id: int | None = None
    tags: list[str] | None = None


class KnowledgeEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    content: str
    company_id: int | None
    tags: list[str] | None
    created_at: datetime
    updated_at: datetime
