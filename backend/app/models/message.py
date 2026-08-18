from datetime import datetime
from typing import Any

from sqlalchemy import Index, JSON, Boolean, ForeignKey, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime, str_enum
from app.enums import DirectionSource, MessageDirection, legacy_is_outgoing
from app.time_utils import utc_now


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "external_id", name="uq_message_chat_external_id"),
        Index("ix_messages_chat_timestamp_id", "chat_id", "timestamp", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(255))
    sender_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    direction: Mapped[MessageDirection] = mapped_column(
        str_enum(MessageDirection),
        default=MessageDirection.INCOMING,
    )
    direction_source: Mapped[DirectionSource] = mapped_column(
        str_enum(DirectionSource),
        default=DirectionSource.NATIVE,
    )
    is_outgoing: Mapped[bool] = mapped_column(Boolean, default=False)  # legacy: True only if direction=outgoing
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    chat: Mapped["Chat"] = relationship(back_populates="messages")
    contact: Mapped["Contact | None"] = relationship(back_populates="messages")
    analysis: Mapped["AIAnalysis | None"] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        uselist=False,
    )
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


def _sync_legacy_direction(target: Message) -> None:
    """Keep direction authoritative; is_outgoing is derived. Honor legacy bool-only inserts."""
    direction = target.direction
    if direction == MessageDirection.UNKNOWN:
        target.is_outgoing = False
        if target.direction_source is None:
            target.direction_source = DirectionSource.UNKNOWN
        return
    if direction == MessageDirection.OUTGOING:
        target.is_outgoing = True
        return
    if direction == MessageDirection.INCOMING and target.is_outgoing:
        target.direction = MessageDirection.OUTGOING
        target.is_outgoing = True
        return
    if direction == MessageDirection.INCOMING:
        target.is_outgoing = False
        return
    target.direction = MessageDirection.OUTGOING if target.is_outgoing else MessageDirection.INCOMING
    target.is_outgoing = legacy_is_outgoing(target.direction)
    if target.direction_source is None:
        target.direction_source = DirectionSource.NATIVE


@event.listens_for(Message, "before_insert")
def _message_before_insert(_mapper: object, _connection: object, target: Message) -> None:
    _sync_legacy_direction(target)


@event.listens_for(Message, "before_update")
def _message_before_update(_mapper: object, _connection: object, target: Message) -> None:
    _sync_legacy_direction(target)
