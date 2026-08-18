"""Map Telegram dialogs/messages to unified inbox models.

Service/action messages are skipped (not ingested). Captions are used as message text
when present, otherwise a privacy-safe placeholder is stored; media itself is fetched
separately by the adapter through the read-only download path.

Direction:
1. native Telegram `out` when present
2. sender user id equals the current account id
3. otherwise unresolved — the message is skipped
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.enums import AttachmentKind, ChatType, DirectionSource, MessageDirection, Platform
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender
from app.services.attachment_storage import MAX_ATTACHMENT_BYTES

MEDIA_PLACEHOLDERS = {
    "photo": "[Photo]",
    "video": "[Video]",
    "voice": "[Voice message]",
    "document": "[File]",
    "sticker": "[Sticker]",
    "contact": "[Contact]",
    "geo": "[Location]",
}

PEER_USER = "user"
PEER_CHAT = "chat"
PEER_CHANNEL = "channel"


@dataclass(frozen=True)
class TelegramAccount:
    id: int


@dataclass(frozen=True)
class TelegramDialogRecord:
    peer_kind: str
    peer_id: int
    title: str | None = None
    is_megagroup: bool = False
    is_broadcast: bool = False


@dataclass(frozen=True)
class TelegramMessageRecord:
    message_id: int
    chat_external_id: str
    chat_name: str
    chat_type: ChatType
    date: datetime
    out: bool | None
    sender_kind: str | None = None
    sender_id: int | None = None
    sender_name: str | None = None
    text: str | None = None
    media_kind: str | None = None
    is_service: bool = False
    media_bytes: int | None = None
    media_mime: str | None = None
    media_filename: str | None = None


DOWNLOADABLE_MEDIA = {"photo", "video", "voice", "document", "sticker"}
IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}


@dataclass(frozen=True)
class TelegramMediaCandidate:
    """What the adapter needs to download one message's media, without Telethon objects."""

    chat_external_id: str
    message_id: int
    kind: AttachmentKind
    filename: str
    byte_size: int | None = None
    content_type: str | None = None

    @property
    def too_large(self) -> bool:
        return self.byte_size is not None and self.byte_size > MAX_ATTACHMENT_BYTES


def attachment_kind_for(media_kind: str | None, mime: str | None) -> AttachmentKind:
    if media_kind == "voice":
        return AttachmentKind.VOICE
    if media_kind in {"photo", "sticker"}:
        return AttachmentKind.IMAGE
    if (mime or "").lower() in IMAGE_MIME_TYPES:
        return AttachmentKind.IMAGE
    return AttachmentKind.FILE


def media_candidate(record: TelegramMessageRecord) -> TelegramMediaCandidate | None:
    if record.is_service or record.media_kind not in DOWNLOADABLE_MEDIA:
        return None
    kind = attachment_kind_for(record.media_kind, record.media_mime)
    name = (record.media_filename or "").strip() or f"{record.media_kind}-{record.message_id}"
    return TelegramMediaCandidate(
        chat_external_id=record.chat_external_id,
        message_id=record.message_id,
        kind=kind,
        filename=name,
        byte_size=record.media_bytes,
        content_type=record.media_mime,
    )


def canonical_peer_id(kind: str, peer_id: int) -> str:
    return f"{kind}:{peer_id}"


def parse_canonical_peer_id(external_id: str) -> tuple[str, int] | None:
    if ":" not in external_id:
        return None
    kind, _, raw = external_id.partition(":")
    if kind not in {PEER_USER, PEER_CHAT, PEER_CHANNEL}:
        return None
    try:
        return kind, int(raw)
    except ValueError:
        return None


def chat_type_for_dialog(record: TelegramDialogRecord) -> ChatType:
    if record.peer_kind == PEER_USER:
        return ChatType.DIRECT
    if record.peer_kind == PEER_CHAT:
        return ChatType.GROUP
    if record.peer_kind == PEER_CHANNEL:
        if record.is_broadcast and not record.is_megagroup:
            return ChatType.CHANNEL
        return ChatType.GROUP
    return ChatType.UNKNOWN


def display_name_for_dialog(record: TelegramDialogRecord) -> str:
    name = (record.title or "").strip()
    if name:
        return name
    return canonical_peer_id(record.peer_kind, record.peer_id)


def map_dialog(record: TelegramDialogRecord) -> UnifiedChat:
    return UnifiedChat(
        platform=Platform.TELEGRAM,
        external_id=canonical_peer_id(record.peer_kind, record.peer_id),
        name=display_name_for_dialog(record),
        chat_type=chat_type_for_dialog(record),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def message_text(record: TelegramMessageRecord) -> str:
    text = (record.text or "").strip()
    if text:
        return text
    if record.media_kind:
        return MEDIA_PLACEHOLDERS.get(record.media_kind, "[File]")
    return ""


def resolve_outgoing(record: TelegramMessageRecord, current_user_id: int | None) -> bool | None:
    if record.out is True:
        return True
    if record.out is False:
        return False
    if (
        current_user_id is not None
        and record.sender_kind == PEER_USER
        and record.sender_id == current_user_id
    ):
        return True
    return None


def sender_external_id(record: TelegramMessageRecord) -> str | None:
    if record.sender_kind in {PEER_USER, PEER_CHANNEL} and record.sender_id is not None:
        return canonical_peer_id(record.sender_kind, record.sender_id)
    return None


def should_attach_contact(record: TelegramMessageRecord, chat_type: ChatType, is_outgoing: bool) -> bool:
    if is_outgoing:
        return False
    if record.sender_kind != PEER_USER or record.sender_id is None:
        return False
    if chat_type == ChatType.CHANNEL:
        return False
    return True


def map_message(
    record: TelegramMessageRecord,
    *,
    current_user_id: int | None,
) -> UnifiedMessage | None:
    if record.is_service:
        return None
    outgoing = resolve_outgoing(record, current_user_id)
    if outgoing is None:
        return None
    text = message_text(record)
    if not text:
        return None
    direction = MessageDirection.OUTGOING if outgoing else MessageDirection.INCOMING
    source = DirectionSource.NATIVE if record.out is not None else DirectionSource.STABLE_ID
    return UnifiedMessage(
        platform=Platform.TELEGRAM,
        external_id=str(record.message_id),
        chat_id=record.chat_external_id,
        chat_name=record.chat_name,
        sender_id=sender_external_id(record),
        sender_name=record.sender_name,
        text=text,
        timestamp=_utc(record.date),
        direction=direction,
        direction_source=source,
        is_outgoing=outgoing,
        attach_contact=should_attach_contact(record, record.chat_type, outgoing),
        raw_data=None,
    )


def map_sender(record: TelegramMessageRecord) -> UnifiedSender | None:
    external_id = sender_external_id(record)
    if not external_id:
        return None
    name = (record.sender_name or "").strip() or external_id
    return UnifiedSender(platform=Platform.TELEGRAM, external_id=external_id, name=name)
