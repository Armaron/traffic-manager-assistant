from __future__ import annotations

import logging
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.base import MessengerAdapter
from app.integrations.typex_errors import TypeXConnectionError
from app.models import Contact
from app.schemas.inbox import TypeXSyncResult
from app.services.message_ingestion import MessageIngestionService

logger = logging.getLogger(__name__)


async def sync_typex_messages(
    session: Session,
    adapter: MessengerAdapter,
    *,
    chat_limit: int,
    message_limit: int,
) -> TypeXSyncResult:
    """Read chats/messages through the adapter and ingest. Never calls AI."""
    started = perf_counter()
    if not await adapter.health_check():
        raise TypeXConnectionError("TypeX is not connected")

    ingestion = MessageIngestionService(session)
    result = TypeXSyncResult()
    contacts_before = session.scalar(select(func.count()).select_from(Contact)) or 0

    chats = (await adapter.get_chats())[:chat_limit]
    result.chats_seen = len(chats)
    for unified_chat in chats:
        _chat, created = ingestion.ingest_chat(unified_chat)
        if created:
            result.chats_created += 1
        messages = (await adapter.get_messages(unified_chat.external_id))[-message_limit:]
        result.messages_seen += len(messages)
        for unified_message in messages:
            _message, message_created = ingestion.ingest_message(unified_message)
            if message_created:
                result.messages_created += 1
            else:
                result.messages_existing += 1

    contacts_after = session.scalar(select(func.count()).select_from(Contact)) or 0
    result.contacts_created = max(0, contacts_after - contacts_before)
    duration_ms = int((perf_counter() - started) * 1000)
    logger.info(
        "typex_sync done chats_seen=%s chats_created=%s messages_seen=%s "
        "messages_created=%s contacts_created=%s duration_ms=%s success=true",
        result.chats_seen,
        result.chats_created,
        result.messages_seen,
        result.messages_created,
        result.contacts_created,
        duration_ms,
    )
    return result
