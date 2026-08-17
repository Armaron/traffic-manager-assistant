from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ChatType, DirectionSource, MessageDirection
from app.models import Chat, Message
from app.schemas.unified import UnifiedChat, UnifiedMessage
from app.services.contact_resolution import resolve_contact
from app.time_utils import utc_now


class MessageIngestionService:
    """Persist unified messenger payloads without creating duplicates."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def ingest_chat(self, payload: UnifiedChat) -> tuple[Chat, bool]:
        chat = self.session.scalar(
            select(Chat).where(
                Chat.platform == payload.platform,
                Chat.external_id == payload.external_id,
            )
        )
        if chat is not None:
            chat.name = payload.name
            chat.chat_type = payload.chat_type
            chat.updated_at = utc_now()
            self.session.flush()
            return chat, False

        chat = Chat(
            platform=payload.platform,
            external_id=payload.external_id,
            name=payload.name,
            chat_type=payload.chat_type,
        )
        self.session.add(chat)
        self.session.flush()
        return chat, True

    def ingest_message(self, payload: UnifiedMessage) -> tuple[Message, bool]:
        existing_chat = self.session.scalar(
            select(Chat).where(
                Chat.platform == payload.platform,
                Chat.external_id == payload.chat_id,
            )
        )
        if existing_chat is not None:
            chat = existing_chat
        else:
            chat, _created = self.ingest_chat(
                UnifiedChat(
                    platform=payload.platform,
                    external_id=payload.chat_id,
                    name=payload.chat_name,
                    chat_type=ChatType.UNKNOWN,
                )
            )

        existing = self.session.scalar(
            select(Message).where(
                Message.chat_id == chat.id,
                Message.external_id == payload.external_id,
            )
        )
        if existing is not None:
            return existing, False

        direction = payload.direction or MessageDirection.INCOMING
        source = payload.direction_source or DirectionSource.UNKNOWN
        is_outgoing = direction == MessageDirection.OUTGOING
        contact_id = None
        if (
            payload.sender_id
            and direction == MessageDirection.INCOMING
            and payload.attach_contact
        ):
            contact, _created = resolve_contact(
                self.session,
                payload.platform,
                payload.sender_id,
                payload.sender_name,
            )
            contact_id = contact.id

        message = Message(
            chat_id=chat.id,
            external_id=payload.external_id,
            sender_external_id=payload.sender_id,
            sender_name=payload.sender_name,
            contact_id=contact_id,
            text=payload.text,
            timestamp=payload.timestamp,
            direction=direction,
            direction_source=source,
            is_outgoing=is_outgoing,
            raw_data=payload.raw_data,
        )
        self.session.add(message)
        if chat.last_message_at is None or payload.timestamp >= chat.last_message_at:
            chat.last_message_at = payload.timestamp
        chat.updated_at = utc_now()
        self.session.flush()
        return message, True
