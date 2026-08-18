from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.enums import ChatType, DirectionSource, MessageDirection, Platform
from app.integrations.typex_direction import TypeXDirectionResult, resolve_typex_direction
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender

CHAT_ID_KEYS = (
    "opaque_ref",
    "feed_id",
    "feed_ref",
    "chat_ref",
    "folder_feed_id",
    "id",
    "chat_id",
    "conversation_id",
    "group_id",
    "gid",
    "target_id",
)
MESSAGE_ID_KEYS = ("message_ref", "record_id", "id", "message_id", "msg_id", "mid")
SENDER_ID_KEYS = (
    "sender_id",
    "user_id",
    "from_id",
    "uid",
    "author_id",
    "fromUserId",
    "typex_id",
    "userId",
    "peer_id",
)
NAME_KEYS = ("name", "title", "display_name", "displayName", "nickname", "chat_name", "feed_name")
TEXT_KEYS = ("text", "content", "body", "message")
TIME_KEYS = (
    "timestamp",
    "time",
    "created_at",
    "createdAt",
    "send_time",
    "sendTime",
    "date",
    "created_time",
    "msg_time",
    "last_message_send_at",
    "send_at",
)
TYPE_KEYS = ("chat_type_label", "type", "chat_type", "chatType", "kind", "feed_type")
CURRENT_USER_ID_KEYS = ("id", "typex_id", "user_id", "uid")
LIST_KEYS = (
    "chats",
    "conversations",
    "messages",
    "items",
    "results",
    "data",
    "users",
    "contacts",
    "feeds",
    "records",
    "folder_feeds",
    "mentions",
    "candidates",
    "files",
)


def extract_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        nested = payload.get("user") or payload.get("me") or payload.get("profile") or payload.get("account")
        if isinstance(nested, dict):
            return [nested]
        if any(key in payload for key in CHAT_ID_KEYS + MESSAGE_ID_KEYS + SENDER_ID_KEYS):
            return [payload]
    return []


def normalize_typex_feed(item: dict[str, Any]) -> dict[str, Any]:
    """Copy TypeX feed/conversation handles onto generic chat id keys."""
    out = dict(item)
    feed_id = first_value(out, CHAT_ID_KEYS)
    if feed_id is not None:
        out.setdefault("id", feed_id)
        out.setdefault("chat_id", feed_id)
    return out


def normalize_typex_record(item: dict[str, Any]) -> dict[str, Any]:
    """Copy TypeX chat-record fields onto the generic message contract."""
    out = dict(item)
    message_id = first_value(out, MESSAGE_ID_KEYS)
    if message_id is not None:
        out["id"] = message_id
    sender_id = first_value(out, SENDER_ID_KEYS)
    if sender_id is not None:
        out.setdefault("sender_id", sender_id)
    send_name = out.get("send_name")
    if isinstance(send_name, str) and send_name.strip():
        out.setdefault("sender_name", send_name.strip())
    send_at = out.get("send_at")
    if send_at is not None:
        out.setdefault("timestamp", send_at)
    return out


def describe_shape(value: Any, *, depth: int = 0, max_depth: int = 6) -> Any:
    """Recursive key/type view. Never includes string values."""
    if depth > max_depth:
        return "max_depth"
    if isinstance(value, dict):
        return {
            str(key): describe_shape(child, depth=depth + 1, max_depth=max_depth)
            for key, child in value.items()
        }
    if isinstance(value, list):
        if not value:
            return []
        first = next((item for item in value if item is not None), None)
        return [describe_shape(first, depth=depth + 1, max_depth=max_depth), f"len={len(value)}"]
    return type(value).__name__


def first_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
        nested = item.get("sender") if key in SENDER_ID_KEYS else None
        if isinstance(nested, dict) and nested.get(key) is not None:
            return nested[key]
        if isinstance(nested, dict) and key == "sender_id" and nested.get("id") is not None:
            return nested["id"]
    return None


def as_str_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e12 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return parse_timestamp(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def map_chat_type(value: Any) -> ChatType:
    if value == 1:
        return ChatType.DIRECT
    if value == 2:
        return ChatType.GROUP
    if isinstance(value, int):
        return ChatType.UNKNOWN
    token = str(value or "").strip()
    lowered = token.lower()
    if token in {"single chat"} or lowered in {"direct", "private", "dm", "p2p", "user", "single chat", "single"}:
        return ChatType.DIRECT
    if token in {"group chat"} or lowered in {"group", "groups", "group chat"}:
        return ChatType.GROUP
    if lowered in {"channel", "broadcast", "room"}:
        return ChatType.CHANNEL
    return ChatType.UNKNOWN


def map_chat(item: dict[str, Any]) -> UnifiedChat | None:
    external_id = as_str_id(first_value(item, CHAT_ID_KEYS))
    if not external_id:
        return None
    name = str(first_value(item, NAME_KEYS) or external_id)
    return UnifiedChat(
        platform=Platform.TYPEX,
        external_id=external_id,
        name=name,
        chat_type=map_chat_type(first_value(item, TYPE_KEYS)),
    )


def _placeholder_text(item: dict[str, Any]) -> str | None:
    media = str(item.get("message_type") or item.get("msg_type") or item.get("type") or "").lower()
    filename = item.get("filename") or item.get("file_name") or item.get("name")
    if "voice" in media or "audio" in media:
        return "[Voice message]"
    if "image" in media or "photo" in media:
        return "[Image]"
    if "sticker" in media:
        return "[Sticker]"
    if "file" in media or "document" in media:
        label = filename if isinstance(filename, str) and filename else "file"
        return f"[File: {label}]"
    if "contact" in media:
        return "[Contact]"
    if media and media not in {"text", "message", "unknown", "direct", "group", "channel"}:
        return f"[{media}]"
    return None


def map_message(
    item: dict[str, Any],
    *,
    chat: UnifiedChat,
    current_user_id: str | None,
    direction_context: Any | None = None,
) -> UnifiedMessage | None:
    item = normalize_typex_record(item)
    external_id = as_str_id(first_value(item, MESSAGE_ID_KEYS))
    timestamp = parse_timestamp(first_value(item, TIME_KEYS))
    if not external_id or timestamp is None:
        return None
    text = first_value(item, TEXT_KEYS)
    text_value = text.strip() if isinstance(text, str) else ""
    if not text_value:
        text_value = _placeholder_text(item) or ""
    if not text_value:
        return None
    sender_id = as_str_id(first_value(item, SENDER_ID_KEYS))
    sender_name_value = first_value(item, NAME_KEYS)
    if sender_name_value == chat.name:
        sender_name = as_str_id(item.get("sender_name") or item.get("from_name") or item.get("send_name"))
    else:
        sender_name = as_str_id(sender_name_value) if sender_name_value else as_str_id(
            item.get("sender_name") or item.get("from_name") or item.get("send_name")
        )
    if direction_context is not None:
        resolved = resolve_typex_direction(item, direction_context)
    else:
        resolved = _direction_without_context(item, sender_id=sender_id, current_user_id=current_user_id)
    return UnifiedMessage(
        platform=Platform.TYPEX,
        external_id=external_id,
        chat_id=chat.external_id,
        chat_name=chat.name,
        sender_id=sender_id,
        sender_name=sender_name,
        text=text_value,
        timestamp=timestamp,
        direction=resolved.direction,
        direction_source=resolved.source,
        is_outgoing=resolved.direction == MessageDirection.OUTGOING,
        raw_data=None,
    )


OUTGOING_BOOL_KEYS = ("is_outgoing", "is_self", "from_me", "outgoing")


def _direction_without_context(
    item: dict[str, Any],
    *,
    sender_id: str | None,
    current_user_id: str | None,
) -> TypeXDirectionResult:
    outgoing = resolve_is_outgoing(item, sender_id=sender_id, current_user_id=current_user_id)
    if outgoing is True:
        for key in OUTGOING_BOOL_KEYS:
            if isinstance(item.get(key), bool):
                return TypeXDirectionResult(MessageDirection.OUTGOING, DirectionSource.NATIVE)
        return TypeXDirectionResult(MessageDirection.OUTGOING, DirectionSource.STABLE_ID)
    if outgoing is False:
        for key in OUTGOING_BOOL_KEYS:
            if isinstance(item.get(key), bool):
                return TypeXDirectionResult(MessageDirection.INCOMING, DirectionSource.NATIVE)
        return TypeXDirectionResult(MessageDirection.INCOMING, DirectionSource.STABLE_ID)
    return TypeXDirectionResult(MessageDirection.UNKNOWN, DirectionSource.UNKNOWN)


def resolve_is_outgoing(
    item: dict[str, Any],
    *,
    sender_id: str | None,
    current_user_id: str | None,
) -> bool | None:
    """Return outgoing flag only from explicit booleans or current-user match.

    Unknown direction is None — never default to incoming.
    """
    for key in OUTGOING_BOOL_KEYS:
        value = item.get(key)
        if isinstance(value, bool):
            return value
    if current_user_id and sender_id:
        return sender_id == current_user_id
    return None


def map_sender(item: dict[str, Any]) -> UnifiedSender | None:
    external_id = as_str_id(first_value(item, SENDER_ID_KEYS + ("id",)))
    if not external_id:
        return None
    name = str(first_value(item, NAME_KEYS) or external_id)
    return UnifiedSender(platform=Platform.TYPEX, external_id=external_id, name=name)


def map_current_user(payload: Any) -> UnifiedSender | None:
    """Map typex.get_me. Prefer stable id over uid when both are present."""
    item: dict[str, Any] | None = None
    if isinstance(payload, dict):
        nested = payload.get("me") or payload.get("user") or payload.get("profile") or payload.get("account")
        item = nested if isinstance(nested, dict) else payload
    if item is None:
        return None
    external_id = as_str_id(first_value(item, CURRENT_USER_ID_KEYS))
    if not external_id:
        return None
    name = str(first_value(item, NAME_KEYS) or external_id)
    return UnifiedSender(platform=Platform.TYPEX, external_id=external_id, name=name)
