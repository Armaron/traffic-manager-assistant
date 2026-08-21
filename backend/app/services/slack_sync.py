from __future__ import annotations

import logging
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.base import MessengerAdapter
from app.integrations.slack import SlackAdapter
from app.integrations.slack_errors import SlackAuthenticationError, SlackError
from app.integrations.slack_mapping import TOMBSTONE_TEXT
from app.integrations.slack_self import apply_slack_self_outgoing
from app.models import Chat, Contact, Message, MessageAttachment
from app.schemas.inbox import SlackSyncResult
from app.schemas.unified import UnifiedAttachment, UnifiedMessage
from app.services.message_ingestion import MessageIngestionService

logger = logging.getLogger(__name__)


def _stored_with_media(session: Session, chat: Chat, message: UnifiedMessage) -> bool:
    existing = session.scalar(
        select(Message).where(
            Message.chat_id == chat.id,
            Message.external_id == message.external_id,
        )
    )
    return existing is not None and bool(existing.attachments)


def _attachment_exists(session: Session, chat: Chat, message: UnifiedMessage, storage_key: str | None) -> bool:
    if not storage_key:
        return False
    existing = session.scalar(
        select(Message).where(
            Message.chat_id == chat.id,
            Message.external_id == message.external_id,
        )
    )
    if existing is None:
        return False
    return session.scalar(
        select(MessageAttachment).where(
            MessageAttachment.message_id == existing.id,
            MessageAttachment.storage_key == storage_key,
        )
    ) is not None


async def _download_files(
    adapter: SlackAdapter | MessengerAdapter,
    chat: Chat,
    unified_message: UnifiedMessage,
    candidates: list[object],
    result: SlackSyncResult,
    session: Session,
) -> None:
    stored: list[UnifiedAttachment] = []
    if _stored_with_media(session, chat, unified_message) and not candidates:
        return
    already = _stored_with_media(session, chat, unified_message)
    for candidate in candidates:
        result.files_seen += 1
        if already:
            result.files_existing += 1
            continue
        if getattr(candidate, "too_large", False):
            result.files_skipped += 1
            continue
        fetch = getattr(adapter, "download_file", None)
        if not callable(fetch):
            result.files_skipped += 1
            continue
        try:
            attachment = await fetch(candidate, unified_message.chat_id)
        except SlackError:
            result.files_failed += 1
            continue
        if attachment is None:
            result.files_failed += 1
            continue
        if _attachment_exists(session, chat, unified_message, attachment.storage_key):
            result.files_existing += 1
            continue
        stored.append(attachment)
        result.files_downloaded += 1
        result.media_downloaded += 1
    if stored:
        unified_message.attachments = stored


async def sync_slack_messages(
    session: Session,
    adapter: MessengerAdapter,
    *,
    chat_limit: int,
    message_limit: int,
) -> SlackSyncResult:
    """Limited Slack reconciliation. Never calls AI. Never writes to Slack."""
    started = perf_counter()
    ensure_ready = getattr(adapter, "ensure_ready_for_sync", None)
    if callable(ensure_ready):
        await ensure_ready()
    elif not await adapter.health_check():
        raise SlackAuthenticationError("Slack authentication failed")

    ingestion = MessageIngestionService(session)
    result = SlackSyncResult()
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
            threads = getattr(adapter, "last_threads_seen", 0)
            result.messages_seen += seen
            result.messages_skipped += skipped
            result.threads_seen += threads
            candidates = getattr(adapter, "last_file_candidates", None) or {}
            for unified_message in messages:
                files = candidates.get(unified_message.external_id) or []
                if files:
                    await _download_files(adapter, chat_row, unified_message, files, result, session)
                _message, message_created = ingestion.ingest_message(unified_message)
                if message_created:
                    result.messages_created += 1
                else:
                    result.messages_existing += 1
                    if ingestion.message_updated:
                        result.messages_updated += 1
        apply_slack_self_outgoing(session)
        contacts_after = session.scalar(select(func.count()).select_from(Contact)) or 0
        result.contacts_created = max(0, contacts_after - contacts_before)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            await close()
    duration_ms = int((perf_counter() - started) * 1000)
    logger.info(
        "slack_sync done chats_seen=%s chats_created=%s messages_seen=%s "
        "messages_created=%s messages_existing=%s messages_skipped=%s "
        "threads_seen=%s files_seen=%s files_downloaded=%s files_existing=%s "
        "files_skipped=%s files_failed=%s contacts_created=%s duration_ms=%s success=true",
        result.chats_seen,
        result.chats_created,
        result.messages_seen,
        result.messages_created,
        result.messages_existing,
        result.messages_skipped,
        result.threads_seen,
        result.files_seen,
        result.files_downloaded,
        result.files_existing,
        result.files_skipped,
        result.files_failed,
        result.contacts_created,
        duration_ms,
    )
    return result


async def ingest_slack_event_message(
    session: Session,
    adapter: SlackAdapter,
    payload: dict[str, object],
    *,
    channel_id: str,
) -> SlackSyncResult:
    """Persist one Socket Mode message event. Own session, no AI."""
    result = SlackSyncResult()
    chat, message, files = await adapter.map_event_message(payload, channel_id=channel_id)
    if chat is None or message is None:
        result.messages_skipped = 1
        return result
    ingestion = MessageIngestionService(session)
    chat_row, chat_created = ingestion.ingest_chat(chat)
    if chat_created:
        result.chats_created = 1
    result.chats_seen = 1
    if files:
        await _download_files(adapter, chat_row, message, files, result, session)
    stored, created = ingestion.ingest_message(message)
    result.messages_seen = 1
    if created:
        result.messages_created = 1
    else:
        result.messages_existing = 1
        if ingestion.message_updated:
            result.messages_updated = 1
    if stored.text == TOMBSTONE_TEXT and not created:
        result.messages_existing = 1
    if message.thread_external_id:
        result.threads_seen = 1
    apply_slack_self_outgoing(session)
    return result
