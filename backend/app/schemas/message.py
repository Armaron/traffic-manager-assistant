from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    chat_id: int
    external_id: str
    text: str
    timestamp: datetime
    sender_external_id: str | None = None
    sender_name: str | None = None
    contact_id: int | None = None
    is_outgoing: bool = False
    raw_data: dict[str, object] | None = None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int
    external_id: str
    sender_external_id: str | None
    sender_name: str | None
    contact_id: int | None
    text: str
    timestamp: datetime
    is_outgoing: bool
    created_at: datetime
    raw_data: dict[str, object] | None = Field(default=None)
