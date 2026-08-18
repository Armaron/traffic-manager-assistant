"""Map Slack conversations/messages to unified inbox models.

Deterministic and network-free. Direction uses the authenticated Slack user id only.
Never uses display-name heuristics. Never stores Slack private file URLs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.enums import AttachmentKind, ChatType, DirectionSource, MessageDirection, Platform
from app.schemas.unified import UnifiedChat, UnifiedMessage
from app.services.attachment_storage import MAX_ATTACHMENT_BYTES

SKIP_SUBTYPES = frozenset(
    {
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "channel_archive",
        "channel_unarchive",
        "group_join",
        "group_leave",
        "group_topic",
        "group_purpose",
        "group_name",
        "group_archive",
        "group_unarchive",
        "pinned_item",
        "unpinned_item",
        "reminder_add",
        "sh_room_created",
        "ekm_access_denied",
        "message_replied",
        "bot_disable",
        "bot_enable",
    }
)

INGEST_SUBTYPES = frozenset(
    {
        "",
        "thread_broadcast",
        "bot_message",
        "file_share",
        "me_message",
    }
)

EDIT_SUBTYPE = "message_changed"
DELETE_SUBTYPE = "message_deleted"
TOMBSTONE_TEXT = "[Deleted Slack message]"

USER_MENTION = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]+)?>")
CHANNEL_MENTION = re.compile(r"<#([A-Z0-9]+)(?:\|([^>]+))?>")
LINK_MENTION = re.compile(r"<(https?://[^>|]+)(?:\|([^>]+))?>")
SPECIAL_MENTION = re.compile(r"<!(channel|here|everyone)(?:\|[^>]+)?>")


@dataclass(frozen=True)
class SlackAuthInfo:
    user_id: str
    team_id: str | None = None


@dataclass(frozen=True)
class SlackUserRecord:
    id: str
    display_name: str


@dataclass(frozen=True)
class SlackConversationRecord:
    id: str
    display_name: str
    is_channel: bool = False
    is_private: bool = False
    is_im: bool = False
    is_mpim: bool = False


@dataclass(frozen=True)
class SlackFileRecord:
    file_id: str
    filename: str
    byte_size: int | None = None
    mimetype: str | None = None

    @property
    def too_large(self) -> bool:
        return self.byte_size is not None and self.byte_size > MAX_ATTACHMENT_BYTES


@dataclass(frozen=True)
class SlackMessageRecord:
    ts: str
    channel_id: str
    chat_name: str
    chat_type: ChatType
    user_id: str | None = None
    sender_name: str | None = None
    text: str | None = None
    subtype: str | None = None
    thread_ts: str | None = None
    reply_count: int = 0
    files: tuple[SlackFileRecord, ...] = ()
    hidden: bool = False
    bot_id: str | None = None
    deleted_ts: str | None = None
    edited_inner: dict[str, object] | None = None


@dataclass(frozen=True)
class SlackFileCandidate:
    file_id: str
    filename: str
    kind: AttachmentKind
    byte_size: int | None = None
    content_type: str | None = None
    message_external_id: str = ""

    @property
    def too_large(self) -> bool:
        return self.byte_size is not None and self.byte_size > MAX_ATTACHMENT_BYTES


def exact_ts(value: object) -> str | None:
    """Preserve Slack ts as the original string. Never identity-cast through float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, Decimal)):
        return format(value, "f")
    return None


def slack_ts_to_datetime(ts: str) -> datetime:
    try:
        seconds = Decimal(ts)
    except (InvalidOperation, ValueError, TypeError):
        return datetime.fromtimestamp(0, tz=timezone.utc)
    whole = int(seconds)
    micros = int((seconds - whole) * 1_000_000)
    return datetime.fromtimestamp(whole, tz=timezone.utc).replace(microsecond=max(0, min(micros, 999999)))


def chat_type_for(record: SlackConversationRecord) -> ChatType:
    if record.is_im:
        return ChatType.DIRECT
    if record.is_mpim:
        return ChatType.GROUP
    if record.is_channel and not record.is_private:
        return ChatType.CHANNEL
    if record.is_private or record.is_channel:
        return ChatType.GROUP
    return ChatType.UNKNOWN


def map_conversation(record: SlackConversationRecord) -> UnifiedChat:
    return UnifiedChat(
        platform=Platform.SLACK,
        external_id=record.id,
        name=record.display_name,
        chat_type=chat_type_for(record),
    )


def slack_mrkdwn_to_text(text: str, users: dict[str, str] | None = None) -> str:
    names = users or {}

    def mention(match: re.Match[str]) -> str:
        uid = match.group(1)
        name = names.get(uid)
        return f"@{name}" if name else "@user"

    def channel(match: re.Match[str]) -> str:
        label = match.group(2)
        return f"#{label}" if label else "#channel"

    def link(match: re.Match[str]) -> str:
        return match.group(2) or match.group(1)

    rendered = USER_MENTION.sub(mention, text)
    rendered = CHANNEL_MENTION.sub(channel, rendered)
    rendered = LINK_MENTION.sub(link, rendered)
    rendered = SPECIAL_MENTION.sub(lambda match: f"@{match.group(1)}", rendered)
    return rendered.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def _rich_text_from_elements(elements: object) -> str:
    if not isinstance(elements, list):
        return ""
    parts: list[str] = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            value = item.get("text")
            if isinstance(value, str) and value:
                parts.append(value)
        elif kind == "link":
            value = item.get("text") or item.get("url")
            if isinstance(value, str) and value:
                parts.append(value)
        elif kind == "user":
            parts.append("@user")
        elif kind in {"rich_text_section", "rich_text_list", "rich_text_preformatted", "rich_text_quote"}:
            nested = _rich_text_from_elements(item.get("elements"))
            if nested:
                parts.append(nested)
        elif kind == "emoji":
            name = item.get("name")
            if isinstance(name, str) and name:
                parts.append(f":{name}:")
    return " ".join(part for part in parts if part).strip()


def extract_text(payload: dict[str, object], users: dict[str, str] | None = None) -> str:
    raw = payload.get("text")
    if isinstance(raw, str) and raw.strip():
        return slack_mrkdwn_to_text(raw, users).strip()
    blocks = payload.get("blocks")
    parts: list[str] = []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "rich_text":
                extracted = _rich_text_from_elements(block.get("elements"))
                if extracted:
                    parts.append(extracted)
    combined = " ".join(parts).strip()
    if combined:
        return combined
    files = payload.get("files")
    if isinstance(files, list) and files:
        first = files[0] if files and isinstance(files[0], dict) else {}
        mimetype = str(first.get("mimetype") or "")
        if mimetype.startswith("image/"):
            return "[Image]"
        return "[File]"
    return "[Slack rich message]"


def file_records(payload: dict[str, object]) -> tuple[SlackFileRecord, ...]:
    files = payload.get("files")
    if not isinstance(files, list):
        return ()
    records: list[SlackFileRecord] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        file_id = item.get("id")
        if not isinstance(file_id, str) or not file_id.strip():
            continue
        name = item.get("name") or item.get("title") or "file"
        size = item.get("size")
        byte_size = int(size) if isinstance(size, int) else None
        mime = item.get("mimetype")
        records.append(
            SlackFileRecord(
                file_id=file_id.strip(),
                filename=str(name),
                byte_size=byte_size,
                mimetype=str(mime) if isinstance(mime, str) else None,
            )
        )
    return tuple(records)


def attachment_kind_for(mime: str | None, filename: str) -> AttachmentKind:
    lowered = (mime or "").lower()
    if lowered.startswith("image/"):
        return AttachmentKind.IMAGE
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in {"png", "jpg", "jpeg", "gif", "webp", "bmp"}:
        return AttachmentKind.IMAGE
    if lowered.startswith("audio/") or suffix in {"m4a", "mp3", "ogg", "oga", "wav", "aac", "amr"}:
        return AttachmentKind.VOICE
    return AttachmentKind.FILE


def file_candidates(record: SlackMessageRecord) -> list[SlackFileCandidate]:
    items: list[SlackFileCandidate] = []
    for file in record.files:
        items.append(
            SlackFileCandidate(
                file_id=file.file_id,
                filename=file.filename,
                kind=attachment_kind_for(file.mimetype, file.filename),
                byte_size=file.byte_size,
                content_type=file.mimetype,
                message_external_id=record.ts,
            )
        )
    return items


def thread_external_id_for(ts: str, thread_ts: str | None) -> str | None:
    if thread_ts and thread_ts != ts:
        return thread_ts
    return None


def is_thread_root(record: SlackMessageRecord) -> bool:
    return thread_external_id_for(record.ts, record.thread_ts) is None


def needs_thread_replies(record: SlackMessageRecord) -> bool:
    return is_thread_root(record) and record.reply_count > 0


def resolve_direction(
    *,
    user_id: str | None,
    current_user_id: str | None,
    subtype: str | None = None,
) -> tuple[MessageDirection, DirectionSource]:
    if current_user_id and user_id and user_id == current_user_id:
        return MessageDirection.OUTGOING, DirectionSource.NATIVE
    if user_id:
        return MessageDirection.INCOMING, DirectionSource.NATIVE
    if subtype == "bot_message":
        return MessageDirection.INCOMING, DirectionSource.NATIVE
    return MessageDirection.UNKNOWN, DirectionSource.UNKNOWN


def should_skip_subtype(subtype: str | None) -> bool:
    if subtype is None:
        return False
    if subtype in SKIP_SUBTYPES:
        return True
    if subtype in {EDIT_SUBTYPE, DELETE_SUBTYPE}:
        return False
    return subtype not in INGEST_SUBTYPES


def safe_raw_data(record: SlackMessageRecord) -> dict[str, object] | None:
    payload: dict[str, object] = {}
    if record.subtype:
        payload["subtype"] = record.subtype
    if record.files:
        payload["file_count"] = len(record.files)
    return payload or None


def map_message(
    record: SlackMessageRecord,
    *,
    current_user_id: str | None,
    users: dict[str, str] | None = None,
) -> UnifiedMessage | None:
    if record.hidden:
        return None
    subtype = record.subtype or ""
    if should_skip_subtype(subtype):
        return None
    if subtype == DELETE_SUBTYPE:
        deleted_ts = record.deleted_ts or record.ts
        if not deleted_ts:
            return None
        return UnifiedMessage(
            platform=Platform.SLACK,
            external_id=deleted_ts,
            chat_id=record.channel_id,
            chat_name=record.chat_name,
            sender_id=record.user_id,
            sender_name=record.sender_name,
            text=TOMBSTONE_TEXT,
            timestamp=slack_ts_to_datetime(deleted_ts),
            direction=MessageDirection.UNKNOWN,
            direction_source=DirectionSource.UNKNOWN,
            attach_contact=False,
            raw_data={"deleted": True},
            thread_external_id=thread_external_id_for(deleted_ts, record.thread_ts),
        )
    ts = exact_ts(record.ts)
    if not ts:
        return None
    direction, source = resolve_direction(
        user_id=record.user_id,
        current_user_id=current_user_id,
        subtype=subtype,
    )
    payload_text = record.text
    if payload_text:
        text = slack_mrkdwn_to_text(payload_text, users).strip() or extract_text(
            {"text": payload_text, "files": [file.__dict__ for file in record.files]},
            users,
        )
    elif record.files:
        kinds = {attachment_kind_for(item.mimetype, item.filename) for item in record.files}
        text = "[Image]" if kinds == {AttachmentKind.IMAGE} else "[File]"
    else:
        text = "[Slack rich message]"
    return UnifiedMessage(
        platform=Platform.SLACK,
        external_id=ts,
        chat_id=record.channel_id,
        chat_name=record.chat_name,
        sender_id=record.user_id,
        sender_name=record.sender_name,
        text=text,
        timestamp=slack_ts_to_datetime(ts),
        direction=direction,
        direction_source=source,
        attach_contact=direction == MessageDirection.INCOMING and bool(record.user_id),
        raw_data=safe_raw_data(record),
        thread_external_id=thread_external_id_for(ts, record.thread_ts),
    )


def message_record_from_payload(
    payload: dict[str, object],
    *,
    channel_id: str,
    chat_name: str,
    chat_type: ChatType,
    sender_name: str | None = None,
    users: dict[str, str] | None = None,
) -> SlackMessageRecord:
    subtype = payload.get("subtype")
    subtype_text = subtype.strip() if isinstance(subtype, str) else None
    inner = payload
    if subtype_text == EDIT_SUBTYPE:
        message = payload.get("message")
        if isinstance(message, dict):
            inner = message
    ts = exact_ts(inner.get("ts") or payload.get("ts")) or ""
    user = inner.get("user") or payload.get("user")
    user_id = user.strip() if isinstance(user, str) else None
    thread_ts = exact_ts(inner.get("thread_ts") or payload.get("thread_ts"))
    reply_count = inner.get("reply_count") or 0
    bot_id = inner.get("bot_id")
    deleted_ts = exact_ts(payload.get("deleted_ts"))
    text_source = inner if isinstance(inner, dict) else payload
    text = extract_text(text_source, users) if subtype_text != DELETE_SUBTYPE else TOMBSTONE_TEXT
    hidden = bool(inner.get("hidden")) if isinstance(inner.get("hidden"), bool) else False
    return SlackMessageRecord(
        ts=ts,
        channel_id=channel_id,
        chat_name=chat_name,
        chat_type=chat_type,
        user_id=user_id,
        sender_name=sender_name,
        text=None if subtype_text == DELETE_SUBTYPE else text,
        subtype=subtype_text,
        thread_ts=thread_ts,
        reply_count=int(reply_count) if isinstance(reply_count, int) else 0,
        files=file_records(inner if isinstance(inner, dict) else payload),
        hidden=hidden,
        bot_id=bot_id.strip() if isinstance(bot_id, str) else None,
        deleted_ts=deleted_ts,
    )
