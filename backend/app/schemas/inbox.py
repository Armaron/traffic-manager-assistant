from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums import ChatType, ConversationStatus, Platform, Priority


class ChatStatusUpdate(BaseModel):
    status: ConversationStatus


class ChatSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: Platform
    name: str
    chat_type: ChatType
    status: ConversationStatus
    last_message_at: datetime | None
    last_message_preview: str | None
    last_sender_name: str | None
    message_count: int
    ai_priority: Priority | None = None
    ai_needs_reply: bool | None = None
    ai_needs_igor: bool | None = None


class SeedResult(BaseModel):
    chats_created: int = 0
    chats_existing: int = 0
    messages_created: int = 0
    messages_existing: int = 0
    chats_total: int = 0
    messages_total: int = 0


class AnalyzeAllResult(BaseModel):
    analyzed: int = 0
    existing: int = 0
    skipped: int = 0


class TypeXHealth(BaseModel):
    mode: str
    connected: bool
    discovery_complete: bool = False
    configured: bool = False
    available_tools_count: int = 0
    allowed_read_tools_count: int = 0
    missing_required_tools: list[str] = []


class TypeXSyncResult(BaseModel):
    chats_seen: int = 0
    chats_created: int = 0
    messages_seen: int = 0
    messages_created: int = 0
    messages_existing: int = 0
    messages_skipped: int = 0
    contacts_created: int = 0


