"""Stable TypeX chat/message identity. opaque_ref and message_ref are session handles."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import DirectionSource, MessageDirection, Platform
from app.integrations.typex_resolver import (
    normalize_display_name,
    typex_conversation_key,
    typex_message_fingerprint,
    typex_message_key,
)
from app.models import AIAnalysis, Chat, Message, MessageAttachment
from app.schemas.unified import UnifiedChat, UnifiedMessage
from app.time_utils import utc_now


def typex_chat_match_key(name: str, chat_type: object) -> tuple[str, str] | None:
    normalized = normalize_display_name(name)
    if not normalized:
        return None
    return (normalized, str(chat_type))


def find_existing_typex_chat(session: Session, payload: UnifiedChat) -> Chat | None:
    by_id = session.scalar(
        select(Chat).where(
            Chat.platform == Platform.TYPEX,
            Chat.external_id == payload.external_id,
        )
    )
    if by_id is not None:
        return by_id
    wanted = typex_chat_match_key(payload.name, payload.chat_type)
    if wanted is None:
        return None
    chats = list(
        session.scalars(
            select(Chat)
            .where(Chat.platform == Platform.TYPEX, Chat.chat_type == payload.chat_type)
            .order_by(Chat.id.asc())
        )
    )
    matches = [chat for chat in chats if typex_chat_match_key(chat.name, chat.chat_type) == wanted]
    if not matches:
        return None
    canonical = matches[0]
    _absorb_typex_chats(session, canonical, matches[1:])
    return canonical


def find_existing_typex_message(session: Session, chat: Chat, payload: UnifiedMessage) -> Message | None:
    by_id = session.scalar(
        select(Message).where(
            Message.chat_id == chat.id,
            Message.external_id == payload.external_id,
        )
    )
    if by_id is not None:
        return by_id
    stable = typex_message_key(payload.timestamp, payload.sender_name, payload.text)
    if stable:
        by_key = session.scalar(
            select(Message).where(Message.chat_id == chat.id, Message.external_id == stable)
        )
        if by_key is not None:
            return by_key
    wanted = typex_message_fingerprint(payload.timestamp, payload.sender_name, payload.text)
    if wanted is None:
        return None
    candidates = list(
        session.scalars(
            select(Message).where(Message.chat_id == chat.id, Message.timestamp == payload.timestamp)
        )
    )
    for message in candidates:
        if typex_message_fingerprint(message.timestamp, message.sender_name, message.text) == wanted:
            return message
    return None


def merge_typex_duplicate_chats(session: Session) -> int:
    """Keep one TypeX chat per exact name+type. Returns deleted chat count."""
    chats = list(
        session.scalars(select(Chat).where(Chat.platform == Platform.TYPEX).order_by(Chat.id.asc()))
    )
    groups: dict[tuple[str, str], list[Chat]] = {}
    for chat in chats:
        key = typex_chat_match_key(chat.name, chat.chat_type)
        if key is None:
            continue
        groups.setdefault(key, []).append(chat)
    deleted = 0
    for _key, rows in groups.items():
        if len(rows) < 2:
            continue
        canonical = rows[0]
        deleted += _absorb_typex_chats(session, canonical, rows[1:])
        stable = typex_conversation_key(canonical.chat_type, canonical.name)
        if stable:
            canonical.external_id = stable
            canonical.updated_at = utc_now()
    session.flush()
    return deleted


def merge_typex_duplicate_messages(session: Session) -> int:
    """Keep one TypeX message per chat+timestamp+sender+text. Returns deleted count."""
    chats = list(session.scalars(select(Chat).where(Chat.platform == Platform.TYPEX).order_by(Chat.id.asc())))
    deleted = 0
    for chat in chats:
        messages = list(
            session.scalars(select(Message).where(Message.chat_id == chat.id).order_by(Message.id.asc()))
        )
        groups: dict[tuple[str, str, str], list[Message]] = {}
        for message in messages:
            fingerprint = typex_message_fingerprint(message.timestamp, message.sender_name, message.text)
            if fingerprint is None:
                continue
            groups.setdefault(fingerprint, []).append(message)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            canonical = rows[0]
            for extra in rows[1:]:
                _adopt_typex_message_fields(session, canonical, extra)
                session.delete(extra)
                deleted += 1
            stable = typex_message_key(canonical.timestamp, canonical.sender_name, canonical.text)
            if stable:
                canonical.external_id = stable
    session.flush()
    return deleted


def apply_self_profile_name_outgoing(session: Session, self_name: str | None) -> int:
    """Mark existing TypeX UNKNOWN messages as outgoing when send_name matches get_me."""
    me = normalize_display_name(self_name)
    if not me:
        return 0
    updated = 0
    rows = list(
        session.scalars(
            select(Message)
            .join(Chat)
            .where(
                Chat.platform == Platform.TYPEX,
                Message.direction == MessageDirection.UNKNOWN,
            )
        )
    )
    for message in rows:
        if normalize_display_name(message.sender_name) != me:
            continue
        message.direction = MessageDirection.OUTGOING
        message.direction_source = DirectionSource.PROFILE_NAME
        message.is_outgoing = True
        analysis = session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == message.id))
        if analysis is not None:
            session.delete(analysis)
        updated += 1
    session.flush()
    return updated


def _absorb_typex_chats(session: Session, canonical: Chat, extras: list[Chat]) -> int:
    deleted = 0
    for extra in extras:
        messages = list(session.scalars(select(Message).where(Message.chat_id == extra.id)))
        for message in messages:
            exists = _existing_typex_message_on_chat(session, canonical, message)
            if exists is not None:
                _adopt_typex_message_fields(session, exists, message)
                session.delete(message)
            else:
                message.chat_id = canonical.id
        if extra.last_message_at and (
            canonical.last_message_at is None or extra.last_message_at > canonical.last_message_at
        ):
            canonical.last_message_at = extra.last_message_at
        session.flush()
        session.delete(extra)
        deleted += 1
    canonical.updated_at = utc_now()
    return deleted


def _existing_typex_message_on_chat(session: Session, chat: Chat, message: Message) -> Message | None:
    by_id = session.scalar(
        select(Message).where(Message.chat_id == chat.id, Message.external_id == message.external_id)
    )
    if by_id is not None:
        return by_id
    wanted = typex_message_fingerprint(message.timestamp, message.sender_name, message.text)
    if wanted is None:
        return None
    candidates = list(
        session.scalars(select(Message).where(Message.chat_id == chat.id, Message.timestamp == message.timestamp))
    )
    for row in candidates:
        if typex_message_fingerprint(row.timestamp, row.sender_name, row.text) == wanted:
            return row
    return None


def _adopt_typex_message_fields(session: Session, canonical: Message, extra: Message) -> None:
    _adopt_typex_attachments(session, canonical, extra)
    if canonical.direction != MessageDirection.UNKNOWN or extra.direction == MessageDirection.UNKNOWN:
        return
    canonical.direction = extra.direction
    canonical.direction_source = extra.direction_source
    canonical.is_outgoing = extra.direction == MessageDirection.OUTGOING
    if extra.direction == MessageDirection.OUTGOING:
        analysis = session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == canonical.id))
        if analysis is not None:
            session.delete(analysis)


def _adopt_typex_attachments(session: Session, canonical: Message, extra: Message) -> None:
    """Attachments cascade with their message, so move them before the duplicate is deleted."""
    moving = list(
        session.scalars(
            select(MessageAttachment).where(MessageAttachment.message_id == extra.id)
        )
    )
    if not moving:
        return
    kept = set(
        session.scalars(
            select(MessageAttachment.storage_key).where(
                MessageAttachment.message_id == canonical.id
            )
        )
    )
    for item in moving:
        if item.storage_key in kept:
            session.delete(item)
            continue
        item.message_id = canonical.id
        kept.add(item.storage_key)
    session.flush()
