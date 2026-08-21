from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime
from app.time_utils import utc_now


class DigestAIResult(Base):
    """Cached explicit AI digest. Never regenerated automatically."""

    __tablename__ = "digest_ai_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_label: Mapped[str] = mapped_column(String(16), default="24h", index=True)
    period_start: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime)
    filters_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=2, index=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
