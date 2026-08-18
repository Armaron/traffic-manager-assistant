from __future__ import annotations

import logging
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import AttachmentKind, MessageDirection
from app.integrations.base import MessengerAdapter
from app.integrations.typex_errors import (
    TypeXConnectionError,
    TypeXError,
    TypeXSyncNotReadyError,
)
from app.media_placeholder import detect_media_placeholder
from app.models import Chat, Contact
from app.schemas.inbox import TypeXSyncResult
from app.schemas.unified import UnifiedAttachment, UnifiedChat, UnifiedMessage
from app.services.message_ingestion import MessageIngestionService
from app.services.typex_chat_identity import (
    apply_self_profile_name_outgoing,
    find_existing_typex_message,
    merge_typex_duplicate_chats,
    merge_typex_duplicate_messages,
)

logger = logging.getLogger(__name__)


def _require_sync_readiness(adapter: MessengerAdapter) -> None:
    readiness_fn = getattr(adapter, "sync_readiness", None)
    if not callable(readiness_fn):
        return
    readiness = readiness_fn()
    if not getattr(readiness, "ready", False):
        raise TypeXSyncNotReadyError(
            getattr(readiness, "reason", None) or "TypeX sync is not ready",
            reason_code=getattr(readiness, "reason_code", None),
        )


def _already_downloaded(session: Session, chat: Chat, message: UnifiedMessage) -> bool:
    existing = find_existing_typex_message(session, chat, message)
    return existing is not None and bool(existing.attachments)


async def _download_by_message_ref(
    adapter: MessengerAdapter,
    chat: UnifiedChat,
    message: UnifiedMessage,
    kind: AttachmentKind,
) -> UnifiedAttachment | None:
    """TypeX often lists no file_ref, but still serves the media by message_ref."""
    fetch = getattr(adapter, "download_message_media", None)
    if not callable(fetch) or not message.external_id:
        return None
    try:
        return await fetch(chat.external_id, message.external_id, kind=kind)
    except TypeXError:
        return None


async def sync_typex_messages(
    session: Session,
    adapter: MessengerAdapter,
    *,
    chat_limit: int,
    message_limit: int,
) -> TypeXSyncResult:
    """Read chats/messages through the adapter and ingest. Never calls AI."""
    started = perf_counter()
    _require_sync_readiness(adapter)
    ensure_ready = getattr(adapter, "ensure_ready_for_sync", None)
    if callable(ensure_ready):
        await ensure_ready()
    elif not await adapter.health_check():
        raise TypeXConnectionError("TypeX is not connected")

    ingestion = MessageIngestionService(session)
    merge_typex_duplicate_chats(session)
    merge_typex_duplicate_messages(session)
    result = TypeXSyncResult()
    contacts_before = session.scalar(select(func.count()).select_from(Contact)) or 0

    chats = (await adapter.get_chats())[:chat_limit]
    result.chats_seen = len(chats)
    for unified_chat in chats:
        chat_row, created = ingestion.ingest_chat(unified_chat)
        if created:
            result.chats_created += 1
        messages = (await adapter.get_messages(unified_chat.external_id))[-message_limit:]
        seen = getattr(adapter, "last_messages_seen", len(messages))
        skipped = getattr(adapter, "last_messages_skipped", 0)
        unknown = getattr(adapter, "last_messages_unknown_direction", None)
        result.messages_seen += seen
        result.messages_skipped += skipped
        if unknown is None:
            unknown = sum(1 for item in messages if item.direction == MessageDirection.UNKNOWN)
        result.messages_unknown_direction += unknown
        result.messages_incoming += sum(1 for item in messages if item.direction == MessageDirection.INCOMING)
        result.messages_outgoing += sum(1 for item in messages if item.direction == MessageDirection.OUTGOING)
        files: list = []
        get_files = getattr(adapter, "get_chat_files", None)
        if callable(get_files):
            files = await get_files(unified_chat.external_id)
        result.files_seen += getattr(adapter, "last_files_seen", len(files))
        result.files_saved += getattr(adapter, "last_files_saved", 0)
        result.files_skipped += getattr(adapter, "last_files_skipped", 0)
        by_ref: dict[str, list] = {}
        for item in files:
            ref = getattr(item, "message_external_id", None)
            if ref:
                by_ref.setdefault(ref, []).append(item)
        for unified_message in messages:
            extra = by_ref.get(unified_message.external_id, [])
            if extra:
                unified_message.attachments = list(unified_message.attachments) + extra
            placeholder = detect_media_placeholder(unified_message.text)
            if (
                placeholder is not None
                and not unified_message.attachments
                and not _already_downloaded(session, chat_row, unified_message)
            ):
                stored = await _download_by_message_ref(adapter, unified_chat, unified_message, placeholder.kind)
                if stored is None:
                    result.media_without_file += 1
                else:
                    unified_message.attachments = [stored]
                    result.files_saved += 1
            _message, message_created = ingestion.ingest_message(unified_message)
            if message_created:
                result.messages_created += 1
            else:
                result.messages_existing += 1

    merge_typex_duplicate_messages(session)

    self_names = list(getattr(adapter, "self_display_names", ()) or ())
    self_names.append(get_settings().typex_self_display_name)
    seen_names: set[str] = set()
    for name in self_names:
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        apply_self_profile_name_outgoing(session, name)

    contacts_after = session.scalar(select(func.count()).select_from(Contact)) or 0
    result.contacts_created = max(0, contacts_after - contacts_before)
    duration_ms = int((perf_counter() - started) * 1000)
    logger.info(
        "typex_sync done chats_seen=%s chats_created=%s messages_seen=%s "
        "messages_created=%s messages_existing=%s messages_skipped=%s "
        "messages_unknown_direction=%s messages_incoming=%s messages_outgoing=%s "
        "files_seen=%s files_saved=%s files_skipped=%s media_without_file=%s "
        "contacts_created=%s duration_ms=%s success=true",
        result.chats_seen,
        result.chats_created,
        result.messages_seen,
        result.messages_created,
        result.messages_existing,
        result.messages_skipped,
        result.messages_unknown_direction,
        result.messages_incoming,
        result.messages_outgoing,
        result.files_seen,
        result.files_saved,
        result.files_skipped,
        result.media_without_file,
        result.contacts_created,
        duration_ms,
    )
    return result
