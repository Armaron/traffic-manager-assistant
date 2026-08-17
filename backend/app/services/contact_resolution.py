from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import Platform
from app.models import Contact, ContactIdentity
from app.time_utils import utc_now


def resolve_contact(
    session: Session,
    platform: Platform,
    external_user_id: str,
    display_name: str | None,
) -> tuple[Contact, bool]:
    """Reuse ContactIdentity for a platform sender. Never merge across platforms."""
    identity = session.scalar(
        select(ContactIdentity).where(
            ContactIdentity.platform == platform,
            ContactIdentity.external_user_id == external_user_id,
        )
    )
    if identity is not None:
        return identity.contact, False

    contact = Contact(name=(display_name or external_user_id).strip() or external_user_id)
    session.add(contact)
    session.flush()
    session.add(
        ContactIdentity(
            contact_id=contact.id,
            platform=platform,
            external_user_id=external_user_id,
            created_at=utc_now(),
        )
    )
    session.flush()
    return contact, True
