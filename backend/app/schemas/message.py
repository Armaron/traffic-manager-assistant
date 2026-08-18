from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.enums import AttachmentKind, DirectionSource, MessageDirection
from app.media_placeholder import detect_media_placeholder


class MessageCreate(BaseModel):
    chat_id: int
    external_id: str
    text: str
    timestamp: datetime
    sender_external_id: str | None = None
    sender_name: str | None = None
    contact_id: int | None = None
    direction: MessageDirection | None = None
    direction_source: DirectionSource | None = None
    is_outgoing: bool = False
    raw_data: dict[str, object] | None = None


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    kind: AttachmentKind
    filename: str
    content_type: str | None = None
    byte_size: int | None = None

    @computed_field
    @property
    def url(self) -> str:
        return f"/api/messages/{self.message_id}/attachments/{self.id}/file"

    @computed_field
    @property
    def thumbnail_url(self) -> str | None:
        if self.kind not in {AttachmentKind.IMAGE, AttachmentKind.MIXED}:
            return None
        return f"/api/messages/{self.message_id}/attachments/{self.id}/thumbnail"


class MediaPlaceholderRead(BaseModel):
    kind: AttachmentKind
    count: int = 1
    caption: str | None = None


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
    direction: MessageDirection | None = None
    direction_source: DirectionSource = DirectionSource.NATIVE
    is_outgoing: bool
    thread_external_id: str | None = None
    created_at: datetime
    raw_data: dict[str, object] | None = Field(default=None)
    attachments: list[AttachmentRead] = Field(default_factory=list)

    @computed_field
    @property
    def media_placeholder(self) -> MediaPlaceholderRead | None:
        placeholder = detect_media_placeholder(self.text)
        if placeholder is None:
            return None
        return MediaPlaceholderRead(
            kind=placeholder.kind,
            count=placeholder.count,
            caption=placeholder.caption,
        )

    @model_validator(mode="after")
    def _sync_direction(self) -> "MessageRead":
        if self.direction is None:
            self.direction = (
                MessageDirection.OUTGOING if self.is_outgoing else MessageDirection.INCOMING
            )
        self.is_outgoing = self.direction == MessageDirection.OUTGOING
        return self


class MessageDirectionUpdate(BaseModel):
    direction: MessageDirection
