from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.enums import ConversationStatus
from app.models import AIAnalysis, Chat, Message
from app.schemas.inbox import ChatSummary
from app.time_utils import utc_now


def message_preview(text: str, limit: int = 72) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def list_chat_summaries(session: Session) -> list[ChatSummary]:
    last_any = (
        select(
            Message.chat_id.label("chat_id"),
            Message.text.label("text"),
            Message.sender_name.label("sender_name"),
            func.row_number()
            .over(
                partition_by=Message.chat_id,
                order_by=(Message.timestamp.desc(), Message.id.desc()),
            )
            .label("rn"),
        )
    ).subquery()

    message_counts = (
        select(
            Message.chat_id.label("chat_id"),
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.chat_id)
        .subquery()
    )

    last_incoming = (
        select(
            Message.id.label("message_id"),
            Message.chat_id.label("chat_id"),
            func.row_number()
            .over(
                partition_by=Message.chat_id,
                order_by=(Message.timestamp.desc(), Message.id.desc()),
            )
            .label("rn"),
        ).where(Message.is_outgoing.is_(False))
    ).subquery()

    stmt = (
        select(
            Chat,
            last_any.c.text,
            last_any.c.sender_name,
            message_counts.c.message_count,
            AIAnalysis.priority,
            AIAnalysis.needs_reply,
            AIAnalysis.needs_igor,
        )
        .outerjoin(last_any, and_(last_any.c.chat_id == Chat.id, last_any.c.rn == 1))
        .outerjoin(message_counts, message_counts.c.chat_id == Chat.id)
        .outerjoin(
            last_incoming,
            and_(last_incoming.c.chat_id == Chat.id, last_incoming.c.rn == 1),
        )
        .outerjoin(AIAnalysis, AIAnalysis.message_id == last_incoming.c.message_id)
        .order_by(Chat.last_message_at.desc().nulls_last(), Chat.id.desc())
    )

    summaries: list[ChatSummary] = []
    for chat, text, sender_name, count, ai_priority, ai_needs_reply, ai_needs_igor in session.execute(
        stmt
    ):
        summaries.append(
            ChatSummary(
                id=chat.id,
                platform=chat.platform,
                name=chat.name,
                chat_type=chat.chat_type,
                status=chat.status,
                last_message_at=chat.last_message_at,
                last_message_preview=message_preview(text) if text else None,
                last_sender_name=sender_name,
                message_count=int(count or 0),
                ai_priority=ai_priority,
                ai_needs_reply=ai_needs_reply,
                ai_needs_igor=ai_needs_igor,
            )
        )
    return summaries


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


def last_incoming_message(session: Session, chat_id: int) -> Message | None:
    return session.scalars(
        select(Message)
        .where(Message.chat_id == chat_id, Message.is_outgoing.is_(False))
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(1)
    ).first()


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
