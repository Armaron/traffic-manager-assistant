"""Delete local inbox rows for one platform. Never calls messengers."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.enums import Platform
from app.models import Chat, Message, MessageAttachment
from app.services.attachment_storage import resolve_storage_key
from app.services.thumbnails import thumbnail_key, thumbnails_root


def clear_platform_chats(session: Session, platform: Platform) -> tuple[int, int]:
    """Remove chats and their messages for `platform`. Returns (chats, messages)."""
    chat_ids = list(session.scalars(select(Chat.id).where(Chat.platform == platform)))
    if not chat_ids:
        return 0, 0
    message_count = int(
        session.scalar(select(func.count()).select_from(Message).where(Message.chat_id.in_(chat_ids))) or 0
    )
    storage_keys = list(
        session.scalars(
            select(MessageAttachment.storage_key)
            .join(Message, Message.id == MessageAttachment.message_id)
            .where(Message.chat_id.in_(chat_ids))
        )
    )
    session.execute(delete(Chat).where(Chat.platform == platform))
    session.flush()
    _delete_orphan_attachment_files(session, storage_keys)
    return len(chat_ids), message_count


def _delete_orphan_attachment_files(session: Session, storage_keys: list[str]) -> None:
    if not storage_keys:
        return
    remaining = set(
        session.scalars(select(MessageAttachment.storage_key).where(MessageAttachment.storage_key.in_(storage_keys)))
    )
    thumbs = thumbnails_root()
    for key in storage_keys:
        if not key or key in remaining:
            continue
        path = resolve_storage_key(key)
        if path is not None:
            path.unlink(missing_ok=True)
        digest = thumbnail_key(key)
        for suffix in (".jpg", ".png"):
            thumb = thumbs / f"{digest}{suffix}"
            if thumb.is_file():
                thumb.unlink(missing_ok=True)
