"""Identify Slack messages sent by the local operator. Name-only, never infers incoming."""

from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import DirectionSource, MessageDirection, Platform
from app.models import AIAnalysis, Chat, Message

logger = logging.getLogger(__name__)

DEFAULT_SELF_NAMES = (
    "Igor Amchislavskii",
    "Igor Amchislavski",
    "Igor Amchislavsky",
    "Igor Amchislavskiy",
)
FIRST_NAME = "igor"
LAST_PREFIX = "amchislavsk"


def is_slack_self_name(sender_name: str | None, extra_names: tuple[str, ...] | None = None) -> bool:
    """True when the Slack sender is the local operator, including spelling variants."""
    tokens = _tokens(sender_name)
    if not tokens:
        return False
    if tokens[0] == FIRST_NAME and any(token.startswith(LAST_PREFIX) for token in tokens[1:]):
        return True
    sender_key = _name_key(sender_name)
    if not sender_key:
        return False
    for candidate in (*DEFAULT_SELF_NAMES, *(extra_names or ()), *_configured_names()):
        other = _name_key(candidate)
        if other and _keys_match(sender_key, other):
            return True
    return False


def apply_slack_self_outgoing(session: Session) -> int:
    """Mark existing Slack messages from Igor as outgoing. Does not override MANUAL."""
    updated = 0
    rows = list(
        session.scalars(
            select(Message)
            .join(Chat)
            .where(
                Chat.platform == Platform.SLACK,
                Message.direction != MessageDirection.OUTGOING,
                Message.direction_source != DirectionSource.MANUAL,
            )
        )
    )
    for message in rows:
        if not is_slack_self_name(message.sender_name):
            continue
        message.direction = MessageDirection.OUTGOING
        message.direction_source = DirectionSource.PROFILE_NAME
        message.is_outgoing = True
        message.contact_id = None
        analysis = session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == message.id))
        if analysis is not None:
            session.delete(analysis)
        updated += 1
    if updated:
        session.flush()
        logger.info("slack_self_outgoing updated=%s", updated)
    return updated


def _configured_names() -> tuple[str, ...]:
    try:
        settings = get_settings()
    except Exception:
        return ()
    names: list[str] = []
    raw = getattr(settings, "slack_self_display_name", None)
    if raw:
        names.extend(part.strip() for part in raw.split(",") if part.strip())
    typex_name = getattr(settings, "typex_self_display_name", None)
    if typex_name:
        names.append(typex_name)
    return tuple(names)


def _tokens(value: str | None) -> list[str]:
    key = _name_key(value)
    if not key:
        return []
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", value or "")
    parts = re.findall(r"[a-zа-яё]+", unicodedata.normalize("NFKD", spaced).encode("ascii", "ignore").decode().lower())
    return parts


def _name_key(value: str | None) -> str:
    if not value or not isinstance(value, str):
        return ""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-zа-яё]+", "", folded)


def _keys_match(left: str, right: str) -> bool:
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return len(shorter) >= 12 and longer.startswith(shorter)
