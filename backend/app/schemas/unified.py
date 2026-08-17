from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import ChatType, Platform


class UnifiedSender(BaseModel):
    platform: Platform
    external_id: str
    name: str


class UnifiedChat(BaseModel):
    platform: Platform
    external_id: str
    name: str
    chat_type: ChatType = ChatType.UNKNOWN


class UnifiedMessage(BaseModel):
    platform: Platform
    external_id: str
    chat_id: str
    chat_name: str
    sender_id: str | None = None
    sender_name: str | None = None
    text: str
    timestamp: datetime
    is_outgoing: bool = False
    raw_data: dict[str, object] | None = Field(default=None)
