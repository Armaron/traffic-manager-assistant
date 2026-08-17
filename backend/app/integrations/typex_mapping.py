from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.enums import ChatType, Platform
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender

CHAT_ID_KEYS = ("id", "chat_id", "conversation_id", "group_id", "gid", "target_id")
MESSAGE_ID_KEYS = ("id", "message_id", "msg_id", "mid")
SENDER_ID_KEYS = ("sender_id", "user_id", "from_id", "uid", "author_id", "fromUserId")
NAME_KEYS = ("name", "title", "display_name", "displayName", "nickname", "chat_name")
TEXT_KEYS = ("text", "content", "body", "message")
TIME_KEYS = ("timestamp", "time", "created_at", "createdAt", "send_time", "sendTime", "date")
TYPE_KEYS = ("type", "chat_type", "chatType", "kind")


def extract_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("chats", "conversations", "messages", "items", "results", "data", "users", "contacts"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if any(key in payload for key in CHAT_ID_KEYS + MESSAGE_ID_KEYS):
            return [payload]
    return []


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
    token = str(value or "").lower()
    if token in {"direct", "private", "dm", "p2p", "user"}:
        return ChatType.DIRECT
    if token in {"group", "groups"}:
        return ChatType.GROUP
    if token in {"channel", "broadcast", "room"}:
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
) -> UnifiedMessage | None:
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
        sender_name = as_str_id(item.get("sender_name") or item.get("from_name"))
    else:
        sender_name = as_str_id(sender_name_value) if sender_name_value else as_str_id(
            item.get("sender_name") or item.get("from_name")
        )
    outgoing_flag = item.get("is_outgoing")
    if outgoing_flag is None:
        outgoing_flag = item.get("is_self") or item.get("from_me") or item.get("outgoing")
    if isinstance(outgoing_flag, bool):
        is_outgoing = outgoing_flag
    elif current_user_id and sender_id:
        is_outgoing = sender_id == current_user_id
    else:
        is_outgoing = False
    return UnifiedMessage(
        platform=Platform.TYPEX,
        external_id=external_id,
        chat_id=chat.external_id,
        chat_name=chat.name,
        sender_id=sender_id,
        sender_name=sender_name,
        text=text_value,
        timestamp=timestamp,
        is_outgoing=is_outgoing,
        raw_data=None,
    )


def map_sender(item: dict[str, Any]) -> UnifiedSender | None:
    external_id = as_str_id(first_value(item, SENDER_ID_KEYS + ("id",)))
    if not external_id:
        return None
    name = str(first_value(item, NAME_KEYS) or external_id)
    return UnifiedSender(platform=Platform.TYPEX, external_id=external_id, name=name)
