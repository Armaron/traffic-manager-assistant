from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums import ChatType, ConversationStatus, Platform


class ChatCreate(BaseModel):
    platform: Platform
    external_id: str
    name: str
    chat_type: ChatType = ChatType.UNKNOWN
    status: ConversationStatus = ConversationStatus.NEW


class ChatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: Platform
    external_id: str
    name: str
    chat_type: ChatType
    status: ConversationStatus
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
