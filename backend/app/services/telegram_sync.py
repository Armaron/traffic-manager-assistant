from __future__ import annotations

import logging
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.base import MessengerAdapter
from app.integrations.telegram_errors import TelegramConnectionError, TelegramError
from app.models import Chat, Contact, Message
from app.schemas.inbox import TelegramSyncResult
from app.schemas.unified import UnifiedAttachment, UnifiedMessage
from app.services.message_ingestion import MessageIngestionService

logger = logging.getLogger(__name__)


def _stored_with_media(session: Session, chat: Chat, message: UnifiedMessage) -> bool:
    """Telegram message ids are stable, so a stored message with files needs no refetch."""
    existing = session.scalar(
        select(Message).where(
            Message.chat_id == chat.id,
            Message.external_id == message.external_id,
        )
    )
    return existing is not None and bool(existing.attachments)


async def _download_media(
    adapter: MessengerAdapter,
    candidate: object,
) -> UnifiedAttachment | None:
    fetch = getattr(adapter, "download_media", None)
    if not callable(fetch):
        return None
    try:
        return await fetch(candidate)
    except TelegramError:
        return None


async def sync_telegram_messages(
    session: Session,
    adapter: MessengerAdapter,
    *,
    chat_limit: int,
    message_limit: int,
) -> TelegramSyncResult:
    """Read chats/messages through the adapter and ingest. Never calls AI."""
    started = perf_counter()
    ensure_ready = getattr(adapter, "ensure_ready_for_sync", None)
    if callable(ensure_ready):
        await ensure_ready()
    elif not await adapter.health_check():
        raise TelegramConnectionError("Telegram is not connected")

    ingestion = MessageIngestionService(session)
    result = TelegramSyncResult()
    contacts_before = session.scalar(select(func.count()).select_from(Contact)) or 0

    try:
        chats = (await adapter.get_chats())[:chat_limit]
        result.chats_seen = len(chats)
        for unified_chat in chats:
            chat_row, created = ingestion.ingest_chat(unified_chat)
            if created:
                result.chats_created += 1
            messages = (await adapter.get_messages(unified_chat.external_id))[-message_limit:]
            seen = getattr(adapter, "last_messages_seen", len(messages))
            skipped = getattr(adapter, "last_messages_skipped", 0)
            result.messages_seen += seen
            result.messages_skipped += skipped
            candidates = getattr(adapter, "last_media_candidates", None) or {}
            for unified_message in messages:
                candidate = candidates.get(unified_message.external_id)
                if candidate is not None:
                    result.media_seen += 1
                    if _stored_with_media(session, chat_row, unified_message):
                        result.media_already_stored += 1
                    elif getattr(candidate, "too_large", False):
                        result.media_skipped_size += 1
                    else:
                        stored = await _download_media(adapter, candidate)
                        if stored is None:
                            result.media_failed += 1
                        else:
                            unified_message.attachments = [stored]
                            result.media_downloaded += 1
                _message, message_created = ingestion.ingest_message(unified_message)
                if message_created:
                    result.messages_created += 1
                else:
                    result.messages_existing += 1

        contacts_after = session.scalar(select(func.count()).select_from(Contact)) or 0
        result.contacts_created = max(0, contacts_after - contacts_before)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            await close()
    duration_ms = int((perf_counter() - started) * 1000)
    logger.info(
        "telegram_sync done chats_seen=%s chats_created=%s messages_seen=%s "
        "messages_created=%s messages_existing=%s messages_skipped=%s "
        "media_seen=%s media_downloaded=%s media_already_stored=%s "
        "media_failed=%s media_skipped_size=%s "
        "contacts_created=%s duration_ms=%s success=true",
        result.chats_seen,
        result.chats_created,
        result.messages_seen,
        result.messages_created,
        result.messages_existing,
        result.messages_skipped,
        result.media_seen,
        result.media_downloaded,
        result.media_already_stored,
        result.media_failed,
        result.media_skipped_size,
        result.contacts_created,
        duration_ms,
    )
    return result
