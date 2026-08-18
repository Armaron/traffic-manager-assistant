from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import AttachmentKind, ChatType, DirectionSource, MessageDirection, Platform


class UnifiedSender(BaseModel):
    platform: Platform
    external_id: str
    name: str


class UnifiedChat(BaseModel):
    platform: Platform
    external_id: str
    name: str
    chat_type: ChatType = ChatType.UNKNOWN


class UnifiedAttachment(BaseModel):
    file_ref: str
    filename: str
    kind: AttachmentKind = AttachmentKind.FILE
    message_external_id: str | None = None
    content_type: str | None = None
    storage_key: str | None = None
    byte_size: int | None = None


class UnifiedMessage(BaseModel):
    platform: Platform
    external_id: str
    chat_id: str
    chat_name: str
    sender_id: str | None = None
    sender_name: str | None = None
    text: str
    timestamp: datetime
    direction: MessageDirection | None = None
    direction_source: DirectionSource = DirectionSource.UNKNOWN
    is_outgoing: bool = False  # legacy: True only when direction=outgoing
    attach_contact: bool = True
    raw_data: dict[str, object] | None = Field(default=None)
    attachments: list[UnifiedAttachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_direction(self) -> "UnifiedMessage":
        if self.direction is None:
            self.direction = (
                MessageDirection.OUTGOING if self.is_outgoing else MessageDirection.INCOMING
            )
            if self.direction_source == DirectionSource.UNKNOWN:
                self.direction_source = DirectionSource.NATIVE
        self.is_outgoing = self.direction == MessageDirection.OUTGOING
        if self.direction != MessageDirection.INCOMING:
            self.attach_contact = False
        return self
