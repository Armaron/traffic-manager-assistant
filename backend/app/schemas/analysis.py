from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import AnalysisCategory, Priority
from app.schemas.chat import ChatRead
from app.schemas.company import CompanyRead
from app.schemas.contact import ContactRead
from app.schemas.knowledge import KnowledgeEntryRead
from app.schemas.message import MessageRead


class ImportantEntities(BaseModel):
    geo: list[str] = Field(default_factory=list)
    traffic_source: list[str] = Field(default_factory=list)
    payment_model: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)


class AIAnalysisResult(BaseModel):
    summary: str
    request: str
    conversation_explanation_ru: str = ""
    next_action_ru: str = ""
    category: AnalysisCategory
    priority: Priority
    needs_reply: bool
    needs_igor: bool
    reason: str
    draft_reply: str | None = None
    important_entities: ImportantEntities = Field(default_factory=ImportantEntities)


class AIAnalysisContext(BaseModel):
    current_message: MessageRead
    recent_messages: list[MessageRead]
    chat: ChatRead
    contact: ContactRead | None = None
    company: CompanyRead | None = None
    knowledge_entries: list[KnowledgeEntryRead] = Field(default_factory=list)
    already_answered: bool = False


class AIAnalysisCreate(BaseModel):
    message_id: int
    summary: str
    request: str
    category: AnalysisCategory
    priority: Priority
    needs_reply: bool
    needs_igor: bool
    reason: str
    draft_reply: str | None = None
    important_entities: ImportantEntities | None = None
    provider: str | None = None
    model: str | None = None


class AIAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    summary: str
    request: str
    conversation_explanation_ru: str | None = None
    next_action_ru: str | None = None
    category: AnalysisCategory
    priority: Priority
    needs_reply: bool
    needs_igor: bool
    reason: str
    draft_reply: str | None
    important_entities: ImportantEntities | None = None
    direction_confirmation_required: bool = False
    draft_is_provisional: bool = False
    provider: str | None
    model: str | None
    created_at: datetime
    updated_at: datetime
