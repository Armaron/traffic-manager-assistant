from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime, str_enum
from app.enums import AnalysisCategory, Priority
from app.time_utils import utc_now


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        unique=True,
    )
    summary: Mapped[str] = mapped_column(Text)
    request: Mapped[str] = mapped_column(Text)
    category: Mapped[AnalysisCategory] = mapped_column(str_enum(AnalysisCategory))
    priority: Mapped[Priority] = mapped_column(str_enum(Priority))
    needs_reply: Mapped[bool] = mapped_column(Boolean)
    needs_igor: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    draft_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    important_entities: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    message: Mapped["Message"] = relationship(back_populates="analysis")
