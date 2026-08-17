from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import DirectionSource, MessageDirection


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
    created_at: datetime
    raw_data: dict[str, object] | None = Field(default=None)

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
