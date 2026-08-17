from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.mock import mock_adapters
from app.integrations.mock_data import build_mock_conversations
from app.models import Chat, Message
from app.schemas.inbox import SeedResult
from app.services.message_ingestion import MessageIngestionService


async def seed_mock_inbox(session: Session) -> SeedResult:
    """Load mock conversations through adapters + ingestion. Safe to run twice."""
    ingestion = MessageIngestionService(session)
    result = SeedResult()
    demo_status_by_chat = {
        (item.chat.platform, item.chat.external_id): item.demo_status
        for item in build_mock_conversations()
    }

    for adapter in mock_adapters():
        chats = await adapter.get_chats()
        for unified_chat in chats:
            chat, created = ingestion.ingest_chat(unified_chat)
            if created:
                result.chats_created += 1
                demo_status = demo_status_by_chat.get(
                    (unified_chat.platform, unified_chat.external_id)
                )
                if demo_status is not None:
                    chat.status = demo_status
            else:
                result.chats_existing += 1

            for unified_message in await adapter.get_messages(unified_chat.external_id):
                _message, message_created = ingestion.ingest_message(unified_message)
                if message_created:
                    result.messages_created += 1
                else:
                    result.messages_existing += 1

    result.chats_total = session.scalar(select(func.count()).select_from(Chat)) or 0
    result.messages_total = session.scalar(select(func.count()).select_from(Message)) or 0
    return result
