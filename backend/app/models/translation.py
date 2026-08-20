from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime, str_enum
from app.enums import TranslationStatus
from app.time_utils import utc_now


class MessageTranslation(Base):
    __tablename__ = "message_translations"
    __table_args__ = (
        UniqueConstraint("message_id", "target_language", name="uq_translation_message_language"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
    )
    target_language: Mapped[str] = mapped_column(String(16))
    source_text_hash: Mapped[str] = mapped_column(String(64))
    source_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[TranslationStatus] = mapped_column(str_enum(TranslationStatus), default=TranslationStatus.PENDING)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    message: Mapped["Message"] = relationship(back_populates="translations")
