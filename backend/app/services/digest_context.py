"""Compact conversation bundles for explicit AI work review. Digest-input only."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import MessageDirection
from app.media_placeholder import detect_media_placeholder
from app.models import Message, MessageAttachment
from app.schemas.digest import DigestItem, DigestPeriod
from app.services.inbox import MEDIA_PREVIEW_LABELS

MAX_MESSAGES_PER_CHAT = 12
MAX_TOTAL_MESSAGES = 80
PRE_PERIOD_MESSAGES = 3
MAX_TEXT_CHARS = 420

ACK_RE = re.compile(
    r"^(?:ok(?:ay)?|thanks?|thx|ty|got it|noted|sure|yes|yep|no|np|cheers|👍+|🙏🏻?)\s*[.!]?\s*$",
    re.I,
)
SIGNAL_RE = re.compile(
    r"(?i)\b(?:q?cpa|q?ftd|rev\s*share|revshare|hybrid|budget|invoice|payouts?|payments?|"
    r"approv(?:e|al|ed)|deadline|report|stats?|statistic|deal|contract|advance|cap|"
    r"geo|cpc|cpm|roi|roas)\b|\$\s?\d|\d+[.,]\d+"
)
FILENAME_RE = re.compile(r"([A-Za-z0-9._-]{3,}\.(?:pdf|xlsx?|csv|png|jpe?g|zip|docx?))", re.I)
FILE_CHROME_RE = re.compile(r"(?i)(?:pdf\s*){2,}|pdfdetails|filedetails|download|preview")


def source_text_hash(text: str | None) -> str:
    """Stable hash of authoritative Message.text. Used for export reproducibility."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def is_ack(text: str | None) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    if len(value) <= 2:
        return True
    return ACK_RE.match(value) is not None


def is_meaningful(text: str | None, direction: MessageDirection | str | None = None) -> bool:
    if not (text or "").strip():
        return False
    if SIGNAL_RE.search(text or ""):
        return True
    if is_ack(text):
        return False
    return True


FUTURE_SEND_RE = re.compile(r"(?i)\b(?:i will send|i'll send|i will share|i'll share|going to send)\b")
SENT_RE = re.compile(r"(?i)\b(?:i sent|i shared|i've sent|i have sent|we sent|i've shared)\b")
FUTURE_CHECK_RE = re.compile(r"(?i)\b(?:i'll check|i will check|let me check|i'll ask|i will ask|i'll confirm)\b")
CHECKED_RE = re.compile(r"(?i)\b(?:i checked|i asked|i confirmed|i've checked)\b")
DONE_RE = re.compile(r"(?i)\b(?:done,? fixed|it's done|fixed it|completed)\b")
CPA_ASK_RE = re.compile(r"(?i)\b(?:can we (?:do|have)|could you|please confirm|confirm)\b.*\bcpa\b|\bcpa\b.*\?")


def describe_outgoing_action(text: str) -> tuple[str, str]:
    """Return (russian action, confidence). Never turns a promise into a completed act."""
    if FUTURE_SEND_RE.search(text):
        return "Игорь сообщил, что отправит материалы.", "explicit"
    if SENT_RE.search(text):
        return "Игорь отправил материалы.", "explicit"
    if FUTURE_CHECK_RE.search(text):
        return "Игорь сообщил, что уточнит вопрос.", "explicit"
    if CHECKED_RE.search(text):
        return "Игорь сообщил, что уже проверил вопрос.", "explicit"
    if DONE_RE.search(text):
        return "Игорь сообщил, что вопрос исправлен.", "explicit"
    snippet = " ".join(text.split())[:120]
    return f"Игорь написал: {snippet}", "strong"


def incoming_is_unapproved_request(text: str) -> bool:
    return CPA_ASK_RE.search(text) is not None or bool(re.search(r"(?i)\bcan you (?:do|confirm)\b", text))


def normalize_digest_text(text: str | None, filename: str | None = None) -> str:
    """Clean file/DOM chrome for AI input only. Does not change stored Message.text."""
    raw = (text or "").strip()
    placeholder = detect_media_placeholder(raw)
    if placeholder is not None:
        label = MEDIA_PREVIEW_LABELS.get(placeholder.kind, "[File]")
        if placeholder.caption:
            return f"{label} {placeholder.caption}".strip()
        if filename:
            return f"{label} {filename}".strip()
        return label
    collapsed = " ".join(raw.split())
    file_name = filename or _filename_in(collapsed)
    if file_name and (FILE_CHROME_RE.search(collapsed.replace(" ", "")) or _duplicated_filename(collapsed, file_name)):
        return f"[File] {file_name}"
    if len(collapsed) > MAX_TEXT_CHARS:
        return collapsed[: MAX_TEXT_CHARS - 1] + "…"
    return collapsed


def load_conversation_bundles(
    session: Session,
    window: DigestPeriod,
    items: list[DigestItem],
) -> dict[int, list[dict]]:
    if not items:
        return {}
    chat_ids = [item.chat_id for item in items]
    lookback = window.start - timedelta(days=7)
    rows = session.scalars(
        select(Message)
        .where(Message.chat_id.in_(chat_ids), Message.timestamp >= lookback, Message.timestamp <= window.end)
        .order_by(Message.chat_id.asc(), Message.timestamp.asc(), Message.id.asc())
    ).all()
    by_chat: dict[int, list[Message]] = {chat_id: [] for chat_id in chat_ids}
    for row in rows:
        by_chat.setdefault(row.chat_id, []).append(row)

    selected: dict[int, list[Message]] = {}
    total = 0
    for item in items:
        picked = _select_for_chat(by_chat.get(item.chat_id, []), window.start, MAX_MESSAGES_PER_CHAT)
        if total + len(picked) > MAX_TOTAL_MESSAGES:
            picked = picked[: max(0, MAX_TOTAL_MESSAGES - total)]
        selected[item.chat_id] = picked
        total += len(picked)
        if total >= MAX_TOTAL_MESSAGES:
            break

    filenames = _filenames_for(session, [msg.id for msgs in selected.values() for msg in msgs])
    bundles: dict[int, list[dict]] = {}
    for chat_id, messages in selected.items():
        bundles[chat_id] = [_bundle_message(msg, window.start, filenames.get(msg.id)) for msg in messages]
    return bundles


def _select_for_chat(messages: list[Message], period_start: datetime, limit: int) -> list[Message]:
    in_period = [msg for msg in messages if msg.timestamp >= period_start]
    pre = [msg for msg in messages if msg.timestamp < period_start]
    meaningful_pre = [msg for msg in pre if is_meaningful(msg.text, msg.direction)][-PRE_PERIOD_MESSAGES:]
    if len(meaningful_pre) < PRE_PERIOD_MESSAGES:
        meaningful_pre = pre[-PRE_PERIOD_MESSAGES:]

    chosen: dict[int, Message] = {}

    def add(msg: Message | None) -> None:
        if msg is None:
            return
        chosen[msg.id] = msg

    meaningful = [msg for msg in in_period if is_meaningful(msg.text, msg.direction)]
    if meaningful:
        add(meaningful[0])
        for msg in meaningful[-5:]:
            add(msg)

    latest_in = _last(in_period, lambda msg: msg.direction != MessageDirection.OUTGOING)
    latest_out = _last(in_period, lambda msg: msg.direction == MessageDirection.OUTGOING)
    add(latest_in)
    add(latest_out)
    for msg in _around(in_period, latest_in):
        add(msg)
    for msg in _around(in_period, latest_out):
        add(msg)

    for msg in in_period:
        if SIGNAL_RE.search(msg.text or ""):
            add(msg)

    period_chosen = sorted(chosen.values(), key=lambda msg: (msg.timestamp, msg.id))
    if len(period_chosen) > limit - len(meaningful_pre):
        keep = {msg.id for msg in (latest_in, latest_out) if msg is not None}
        keep.update(msg.id for msg in meaningful[-5:])
        keep.update(msg.id for msg in in_period if SIGNAL_RE.search(msg.text or ""))
        ranked = [msg for msg in period_chosen if msg.id in keep] + [msg for msg in period_chosen if msg.id not in keep]
        period_chosen = ranked[: max(0, limit - len(meaningful_pre))]

    combined = meaningful_pre + period_chosen
    combined.sort(key=lambda msg: (msg.timestamp, msg.id))
    return combined[:limit]


def _bundle_message(message: Message, period_start: datetime, filename: str | None) -> dict:
    text = normalize_digest_text(message.text, filename)
    return {
        "id": message.id,
        "timestamp": message.timestamp.isoformat() if message.timestamp else None,
        "direction": message.direction.value,
        "inside_period": message.timestamp >= period_start,
        "sender_name": message.sender_name or "",
        "text": text,
        "low_information": is_ack(message.text),
    }


def _filenames_for(session: Session, message_ids: list[int]) -> dict[int, str]:
    if not message_ids:
        return {}
    rows = session.scalars(select(MessageAttachment).where(MessageAttachment.message_id.in_(message_ids))).all()
    names: dict[int, str] = {}
    for row in rows:
        if row.filename and row.message_id not in names:
            names[row.message_id] = row.filename
    return names


def _filename_in(text: str) -> str | None:
    match = FILENAME_RE.search(text)
    return match.group(1) if match else None


def _duplicated_filename(text: str, filename: str) -> bool:
    return text.lower().count(filename.lower()) >= 2 or filename.lower().replace(".", "") in re.sub(r"[\s.]", "", text.lower())


def _last(messages: list[Message], predicate) -> Message | None:
    for msg in reversed(messages):
        if predicate(msg):
            return msg
    return None


def _around(messages: list[Message], target: Message | None) -> list[Message]:
    if target is None:
        return []
    index = next((i for i, msg in enumerate(messages) if msg.id == target.id), None)
    if index is None:
        return []
    start = max(0, index - 1)
    end = min(len(messages), index + 2)
    return messages[start:end]
