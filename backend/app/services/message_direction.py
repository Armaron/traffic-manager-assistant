from sqlalchemy.orm import Session

from app.enums import DirectionSource, MessageDirection
from app.models import Message


def set_message_direction(session: Session, message_id: int, direction: MessageDirection) -> Message | None:
    """Local metadata only. Never calls messengers. Never creates a Contact from a name."""
    message = session.get(Message, message_id)
    if message is None:
        return None
    if direction == MessageDirection.UNKNOWN:
        message.direction = MessageDirection.UNKNOWN
        message.direction_source = DirectionSource.UNKNOWN
        message.is_outgoing = False
        session.flush()
        return message
    message.direction = direction
    message.direction_source = DirectionSource.MANUAL
    message.is_outgoing = direction == MessageDirection.OUTGOING
    if direction == MessageDirection.OUTGOING:
        message.contact_id = None
    session.flush()
    return message
