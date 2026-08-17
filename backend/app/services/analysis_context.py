from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Chat, Contact, KnowledgeEntry, Message
from app.schemas.analysis import AIAnalysisContext
from app.schemas.chat import ChatRead
from app.schemas.company import CompanyRead
from app.schemas.contact import ContactRead
from app.schemas.knowledge import KnowledgeEntryRead
from app.schemas.message import MessageRead

RECENT_MESSAGE_LIMIT = 15


def build_analysis_context(session: Session, message_id: int) -> AIAnalysisContext:
    message = session.get(Message, message_id)
    if message is None:
        raise ValueError("Message not found")

    chat = session.get(Chat, message.chat_id)
    if chat is None:
        raise ValueError("Chat not found")

    recent = list(
        session.scalars(
            select(Message)
            .where(Message.chat_id == chat.id)
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .limit(RECENT_MESSAGE_LIMIT)
        ).all()
    )
    recent.reverse()
    if all(item.id != message.id for item in recent):
        recent = [message, *recent][:RECENT_MESSAGE_LIMIT]

    contact = session.get(Contact, message.contact_id) if message.contact_id else None
    company = contact.company if contact is not None else None

    knowledge_query = select(KnowledgeEntry).limit(10)
    if company is not None:
        knowledge_query = (
            select(KnowledgeEntry)
            .where(
                or_(
                    KnowledgeEntry.company_id == company.id,
                    KnowledgeEntry.company_id.is_(None),
                )
            )
            .limit(10)
        )
    else:
        knowledge_query = (
            select(KnowledgeEntry).where(KnowledgeEntry.company_id.is_(None)).limit(10)
        )
    knowledge_entries = list(session.scalars(knowledge_query).all())

    return AIAnalysisContext(
        current_message=MessageRead.model_validate(message),
        recent_messages=[MessageRead.model_validate(item) for item in recent],
        chat=ChatRead.model_validate(chat),
        contact=ContactRead.model_validate(contact) if contact else None,
        company=CompanyRead.model_validate(company) if company else None,
        knowledge_entries=[KnowledgeEntryRead.model_validate(item) for item in knowledge_entries],
    )
