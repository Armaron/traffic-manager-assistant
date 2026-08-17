from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime, str_enum
from app.enums import Platform
from app.time_utils import utc_now


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    )
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    company: Mapped["Company | None"] = relationship(back_populates="contacts")
    identities: Mapped[list["ContactIdentity"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["Message"]] = relationship(back_populates="contact")


class ContactIdentity(Base):
    """Links one contact to messenger accounts across platforms."""

    __tablename__ = "contact_identities"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "external_user_id",
            name="uq_contact_identity_platform_user",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(str_enum(Platform))
    external_user_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    contact: Mapped[Contact] = relationship(back_populates="identities")
