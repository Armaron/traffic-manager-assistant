from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime, str_enum
from app.enums import CompanyType
from app.time_utils import utc_now


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    company_type: Mapped[CompanyType] = mapped_column(str_enum(CompanyType))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company")
    knowledge_entries: Mapped[list["KnowledgeEntry"]] = relationship(
        back_populates="company"
    )
