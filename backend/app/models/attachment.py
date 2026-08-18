from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime, str_enum
from app.enums import AttachmentKind
from app.time_utils import utc_now


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        UniqueConstraint("message_id", "storage_key", name="uq_attachment_message_storage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[AttachmentKind] = mapped_column(str_enum(AttachmentKind))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512))
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    message: Mapped["Message"] = relationship(back_populates="attachments")
