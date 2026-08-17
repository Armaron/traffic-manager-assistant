from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums import ChatType, ConversationStatus, Platform


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


class SeedResult(BaseModel):
    chats_created: int = 0
    chats_existing: int = 0
    messages_created: int = 0
    messages_existing: int = 0
    chats_total: int = 0
    messages_total: int = 0
