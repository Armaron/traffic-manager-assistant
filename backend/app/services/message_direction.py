from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import DirectionSource, MessageDirection
from app.models import AIAnalysis, Message


def set_message_direction(session: Session, message_id: int, direction: MessageDirection) -> Message | None:
    """Local metadata only. Never calls messengers. Never creates a Contact from a name."""
    message = session.get(Message, message_id)
    if message is None:
        return None
    if message.direction == direction:
        return message

    if direction == MessageDirection.UNKNOWN:
        message.direction = MessageDirection.UNKNOWN
        message.direction_source = DirectionSource.UNKNOWN
        message.is_outgoing = False
    else:
        message.direction = direction
        message.direction_source = DirectionSource.MANUAL
        message.is_outgoing = direction == MessageDirection.OUTGOING
        if direction == MessageDirection.OUTGOING:
            message.contact_id = None

    analysis = session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == message.id))
    if analysis is not None:
        session.delete(analysis)
    session.flush()
    return message
