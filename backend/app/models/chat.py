from datetime import datetime

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime, str_enum
from app.enums import ChatType, ConversationStatus, Platform
from app.time_utils import utc_now


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_chat_platform_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[Platform] = mapped_column(str_enum(Platform))
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    chat_type: Mapped[ChatType] = mapped_column(
        str_enum(ChatType),
        default=ChatType.UNKNOWN,
    )
    status: Mapped[ConversationStatus] = mapped_column(
        str_enum(ConversationStatus, length=32),
        default=ConversationStatus.NEW,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat",
        cascade="all, delete-orphan",
    )
