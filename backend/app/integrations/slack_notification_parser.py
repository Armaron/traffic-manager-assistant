"""Parse Slack Desktop toast text into a local inbox event.

Never invents Slack channel IDs (C/D/G...), user IDs, or thread timestamps.
Keep in sync with windows-notification-listener SlackNotificationParser.cs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from app.integrations.slack_notification_source import (
    BROWSER_UNKNOWN,
    OTHER,
    SLACK_DESKTOP,
    NotificationAppIdentity,
    classify_notification_source,
    source_id_for,
)

AGGREGATE_RE = re.compile(
    r"^(?:"
    r"\d+\s+new messages?|"
    r"new activity(?: in slack)?|"
    r"you have (?:unread |new )?messages?|"
    r"unread messages?|"
    r"new messages? in slack|"
    r"slack$"
    r")\.?$",
    re.IGNORECASE,
)
CHANNEL_PREFIX_RE = re.compile(r"^(?:channel:\s*|#)(.+)$", re.IGNORECASE)
SENDER_BODY_RE = re.compile(r"^(.{1,80}?):\s+(.+)$", re.DOTALL)
THREAD_HINT_RE = re.compile(r"\breplied to a thread\b|\bin a thread\b", re.IGNORECASE)
NON_SLUG_RE = re.compile(r"[^a-z0-9]+")
SLACK_API_ID_RE = re.compile(r"^[CDG][A-Z0-9]{8,}$")


@dataclass(frozen=True)
class SlackNotificationParseResult:
    source_kind: str
    skip_reason: str | None
    sender_name: str | None
    text: str | None
    conversation_hint: str | None
    conversation_kind: str
    mapping_confidence: str
    is_truncated: bool
    notification_external_id: str
    chat_external_id: str | None
    thread_hint: str | None
    source_id: str


def _normalize_line(value: str | None) -> str:
    return re.sub(r"[ \t]+", " ", str(value or "").replace("\r\n", "\n")).strip()


def _lines(text_elements: list[str] | tuple[str, ...]) -> list[str]:
    return [line for line in (_normalize_line(item) for item in text_elements) if line]


def is_aggregate_text(*parts: str | None) -> bool:
    for part in parts:
        value = _normalize_line(part)
        if value and AGGREGATE_RE.match(value):
            return True
    return False


def detect_truncation(text: str, *, flagged: bool = False) -> bool:
    if flagged:
        return True
    stripped = text.rstrip()
    if stripped.endswith("…") or stripped.endswith("..."):
        return True
    return len(stripped) >= 220


def slug_for(value: str) -> str:
    lowered = _normalize_line(value).lower().lstrip("#")
    slug = NON_SLUG_RE.sub("-", lowered).strip("-")
    return (slug or "unknown")[:80]


def notification_chat_id(*, kind: str, hint: str) -> str:
    prefix = "channel" if kind == "channel" else "dm"
    return f"notification:{prefix}:{slug_for(hint)}"


def notification_message_id(
    *,
    source_id: str,
    notification_id: str | None,
    created_at: str | None,
    sender_name: str | None,
    text: str,
) -> str:
    if notification_id and source_id:
        material = f"{source_id}\n{notification_id}\n{created_at or ''}"
    else:
        bucket = (created_at or "")[:16]
        material = f"{source_id}\n{sender_name or ''}\n{text}\n{bucket}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"n_{digest}"


def _looks_like_slack_api_id(value: str | None) -> bool:
    return bool(value and SLACK_API_ID_RE.match(value))


def parse_slack_notification(
    text_elements: list[str] | tuple[str, ...],
    *,
    identity: NotificationAppIdentity,
    notification_id: str | None = None,
    created_at: str | None = None,
    extra_source_ids: tuple[str, ...] | list[str] = (),
    truncation_flagged: bool = False,
) -> SlackNotificationParseResult:
    source_kind = classify_notification_source(identity, extra_source_ids=extra_source_ids)
    source_id = source_id_for(identity)
    lines = _lines(text_elements)
    empty_id = notification_message_id(
        source_id=source_id,
        notification_id=notification_id,
        created_at=created_at,
        sender_name=None,
        text="",
    )
    if source_kind != SLACK_DESKTOP:
        reason = "unrelated" if source_kind == OTHER else "browser_unknown"
        return SlackNotificationParseResult(
            source_kind=source_kind,
            skip_reason=reason,
            sender_name=None,
            text=None,
            conversation_hint=None,
            conversation_kind="direct",
            mapping_confidence="low",
            is_truncated=False,
            notification_external_id=empty_id,
            chat_external_id=None,
            thread_hint=None,
            source_id=source_id,
        )
    if not lines:
        return SlackNotificationParseResult(
            source_kind=source_kind,
            skip_reason="empty",
            sender_name=None,
            text=None,
            conversation_hint=None,
            conversation_kind="direct",
            mapping_confidence="low",
            is_truncated=False,
            notification_external_id=empty_id,
            chat_external_id=None,
            thread_hint=None,
            source_id=source_id,
        )
    if any(is_aggregate_text(line) for line in lines) or is_aggregate_text(" ".join(lines)):
        return SlackNotificationParseResult(
            source_kind=source_kind,
            skip_reason="aggregate",
            sender_name=None,
            text=None,
            conversation_hint=None,
            conversation_kind="direct",
            mapping_confidence="low",
            is_truncated=False,
            notification_external_id=empty_id,
            chat_external_id=None,
            thread_hint=None,
            source_id=source_id,
        )

    title = lines[0]
    rest = lines[1:]
    if title.lower() == "slack" and rest:
        title = rest[0]
        rest = rest[1:]
        if is_aggregate_text(title, *rest, " ".join([title, *rest])):
            return SlackNotificationParseResult(
                source_kind=source_kind,
                skip_reason="aggregate",
                sender_name=None,
                text=None,
                conversation_hint=None,
                conversation_kind="direct",
                mapping_confidence="low",
                is_truncated=False,
                notification_external_id=empty_id,
                chat_external_id=None,
                thread_hint=None,
                source_id=source_id,
            )

    conversation_kind = "direct"
    conversation_hint: str | None = None
    sender_name: str | None = None
    body = "\n".join(rest)

    channel_match = CHANNEL_PREFIX_RE.match(title)
    if channel_match:
        conversation_kind = "channel"
        conversation_hint = channel_match.group(1).strip()
        sender_match = SENDER_BODY_RE.match(body)
        if sender_match:
            sender_name = sender_match.group(1).strip()
            body = sender_match.group(2).strip()
    elif not rest and SENDER_BODY_RE.match(title):
        sender_match = SENDER_BODY_RE.match(title)
        assert sender_match is not None
        sender_name = sender_match.group(1).strip()
        body = sender_match.group(2).strip()
        conversation_hint = sender_name
    else:
        sender_name = title
        conversation_hint = title
        if not body and rest:
            body = "\n".join(rest)

    body = _normalize_line(body)
    if not body:
        return SlackNotificationParseResult(
            source_kind=source_kind,
            skip_reason="empty",
            sender_name=sender_name,
            text=None,
            conversation_hint=conversation_hint,
            conversation_kind=conversation_kind,
            mapping_confidence="low",
            is_truncated=False,
            notification_external_id=empty_id,
            chat_external_id=None,
            thread_hint=None,
            source_id=source_id,
        )

    if is_aggregate_text(body):
        return SlackNotificationParseResult(
            source_kind=source_kind,
            skip_reason="aggregate",
            sender_name=sender_name,
            text=None,
            conversation_hint=conversation_hint,
            conversation_kind=conversation_kind,
            mapping_confidence="low",
            is_truncated=False,
            notification_external_id=empty_id,
            chat_external_id=None,
            thread_hint=None,
            source_id=source_id,
        )

    hint = conversation_hint or sender_name or "unknown"
    if conversation_kind == "channel" and sender_name and body:
        confidence = "high"
    elif conversation_kind == "direct" and sender_name and body:
        confidence = "medium"
    else:
        confidence = "low"

    if confidence == "low":
        return SlackNotificationParseResult(
            source_kind=source_kind,
            skip_reason="low_confidence",
            sender_name=sender_name,
            text=body,
            conversation_hint=conversation_hint,
            conversation_kind=conversation_kind,
            mapping_confidence=confidence,
            is_truncated=detect_truncation(body, flagged=truncation_flagged),
            notification_external_id=empty_id,
            chat_external_id=None,
            thread_hint=None,
            source_id=source_id,
        )

    chat_id = notification_chat_id(kind=conversation_kind, hint=hint)
    if _looks_like_slack_api_id(chat_id) or _looks_like_slack_api_id(hint):
        chat_id = notification_chat_id(kind=conversation_kind, hint=f"hint-{slug_for(hint)}")

    message_id = notification_message_id(
        source_id=source_id,
        notification_id=notification_id,
        created_at=created_at,
        sender_name=sender_name,
        text=body,
    )
    thread_hint = "thread" if THREAD_HINT_RE.search("\n".join(lines)) else None
    return SlackNotificationParseResult(
        source_kind=source_kind,
        skip_reason=None,
        sender_name=sender_name,
        text=body,
        conversation_hint=conversation_hint,
        conversation_kind=conversation_kind,
        mapping_confidence=confidence,
        is_truncated=detect_truncation(body, flagged=truncation_flagged),
        notification_external_id=message_id,
        chat_external_id=chat_id,
        thread_hint=thread_hint,
        source_id=source_id,
    )


def parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed
