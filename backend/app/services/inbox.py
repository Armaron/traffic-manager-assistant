from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ConversationStatus
from app.models import Chat, Message
from app.schemas.inbox import ChatSummary
from app.time_utils import utc_now


def message_preview(text: str, limit: int = 72) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def list_chat_summaries(session: Session) -> list[ChatSummary]:
    chats = session.scalars(
        select(Chat).order_by(Chat.last_message_at.desc().nulls_last(), Chat.id.desc())
    ).all()
    return [_to_summary(session, chat) for chat in chats]


def get_chat(session: Session, chat_id: int) -> Chat | None:
    return session.get(Chat, chat_id)


def list_messages(session: Session, chat_id: int) -> list[Message]:
    return list(
        session.scalars(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.timestamp.asc(), Message.id.asc())
        ).all()
    )


def update_chat_status(
    session: Session,
    chat_id: int,
    status: ConversationStatus,
) -> Chat | None:
    chat = session.get(Chat, chat_id)
    if chat is None:
        return None
    chat.status = status
    chat.updated_at = utc_now()
    session.flush()
    return chat


def _to_summary(session: Session, chat: Chat) -> ChatSummary:
    last = session.scalars(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(1)
    ).first()
    count = session.scalar(
        select(func.count()).select_from(Message).where(Message.chat_id == chat.id)
    )
    return ChatSummary(
        id=chat.id,
        platform=chat.platform,
        name=chat.name,
        chat_type=chat.chat_type,
        status=chat.status,
        last_message_at=chat.last_message_at,
        last_message_preview=message_preview(last.text) if last else None,
        last_sender_name=last.sender_name if last else None,
        message_count=int(count or 0),
    )
