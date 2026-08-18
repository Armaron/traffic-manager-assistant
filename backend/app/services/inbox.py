from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.enums import AttachmentKind, ConversationStatus, MessageDirection
from app.media_placeholder import detect_media_placeholder
from app.models import AIAnalysis, Chat, Message
from app.schemas.inbox import ChatSummary
from app.time_utils import utc_now

ACTIONABLE_DIRECTIONS = (MessageDirection.INCOMING, MessageDirection.UNKNOWN)
MEDIA_PREVIEW_LABELS = {
    AttachmentKind.IMAGE: "[Image]",
    AttachmentKind.MIXED: "[Image]",
    AttachmentKind.VOICE: "[Voice]",
    AttachmentKind.FILE: "[File]",
}


def message_preview(text: str, limit: int = 72) -> str:
    placeholder = detect_media_placeholder(text)
    if placeholder is not None:
        label = MEDIA_PREVIEW_LABELS[placeholder.kind]
        text = f"{label} {placeholder.caption}" if placeholder.caption else label
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

    last_actionable = (
        select(
            Message.id.label("message_id"),
            Message.chat_id.label("chat_id"),
            func.row_number()
            .over(
                partition_by=Message.chat_id,
                order_by=(Message.timestamp.desc(), Message.id.desc()),
            )
            .label("rn"),
        ).where(Message.direction.in_(ACTIONABLE_DIRECTIONS))
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
            last_actionable,
            and_(last_actionable.c.chat_id == Chat.id, last_actionable.c.rn == 1),
        )
        .outerjoin(AIAnalysis, AIAnalysis.message_id == last_actionable.c.message_id)
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
            .options(selectinload(Message.attachments))
            .where(Message.chat_id == chat_id)
            .order_by(Message.timestamp.asc(), Message.id.asc())
        ).all()
    )


def latest_actionable_message(session: Session, chat_id: int) -> Message | None:
    """Newest INCOMING or UNKNOWN message. OUTGOING is never a target."""
    return session.scalars(
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.direction.in_(ACTIONABLE_DIRECTIONS),
        )
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(1)
    ).first()


def analysis_target_message(session: Session, chat_id: int) -> Message | None:
    return latest_actionable_message(session, chat_id)


def has_outgoing_after_message(session: Session, message: Message) -> bool:
    """Deterministic already-answered check. Ties on timestamp fall back to id order."""
    later = session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.chat_id == message.chat_id,
            Message.direction == MessageDirection.OUTGOING,
            or_(
                Message.timestamp > message.timestamp,
                and_(Message.timestamp == message.timestamp, Message.id > message.id),
            ),
        )
    )
    return bool(later)


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
