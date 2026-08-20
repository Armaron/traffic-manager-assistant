"""Local Slack Windows notification ingest. No Slack SDK, tokens, cookies, or writes."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, Settings, get_settings
from app.enums import ChatType, DirectionSource, MessageDirection, Platform
from app.integrations.slack_notification_parser import (
    is_aggregate_text,
    notification_chat_id,
    parse_created_at,
)
from app.integrations.slack_notification_source import configured_source_ids
from app.models import Contact
from app.schemas.inbox import SlackSyncResult
from app.schemas.slack_notifications import SlackNotificationEvent, SlackNotificationHealth
from app.schemas.unified import UnifiedChat, UnifiedMessage
from app.services.message_ingestion import MessageIngestionService
from app.services.sync_runtime import get_sync_runtime, inbox_changed
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

TOKEN_HEADER = "X-TMA-Local-Token"
TOKEN_FILE = DATA_DIR / "slack_notification_token"
HEARTBEAT_STALE = timedelta(seconds=45)
MAX_TEXT = 8000
SAFE_RAW_KEYS = frozenset(
    {
        "source",
        "ingestion_source",
        "notification_truncated",
        "timestamp_kind",
        "mapping_confidence",
        "thread_hint",
        "conversation_hint",
    }
)

CHAT_TYPES = {
    "direct": ChatType.DIRECT,
    "group": ChatType.GROUP,
    "channel": ChatType.CHANNEL,
}


@dataclass
class NotificationCaptureState:
    last_heartbeat_at: datetime | None = None
    last_event_at: datetime | None = None
    helper_connected: bool = False
    permission_allowed: bool = False
    slack_source_detected: bool = False
    listener_access: str = "unspecified"


_state = NotificationCaptureState()


def capture_state() -> NotificationCaptureState:
    return _state


def reset_notification_capture_state() -> None:
    global _state
    _state = NotificationCaptureState()


def slack_notification_capture_enabled(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(cfg.slack_notification_capture_enabled)


def resolve_slack_notification_token(settings: Settings | None = None) -> str | None:
    cfg = settings or get_settings()
    env_token = (cfg.slack_notification_local_token or "").strip()
    if env_token:
        return env_token
    if TOKEN_FILE.is_file():
        stored = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    return None


def ensure_slack_notification_token(settings: Settings | None = None) -> str | None:
    """Create a local app token for the Windows helper. This is not a Slack credential."""
    cfg = settings or get_settings()
    existing = resolve_slack_notification_token(cfg)
    if existing:
        return existing
    if not slack_notification_capture_enabled(cfg):
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    logger.info("slack notification local token stored under data/")
    return token


def token_matches(provided: str, settings: Settings | None = None) -> bool:
    expected = resolve_slack_notification_token(settings)
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided, expected)


def refresh_notification_connection(now: datetime | None = None) -> None:
    moment = now or utc_now()
    last = _state.last_heartbeat_at
    if last is None:
        _state.helper_connected = False
        return
    if last.tzinfo is None:
        last = last.replace(tzinfo=moment.tzinfo)
    _state.helper_connected = (moment - last) <= HEARTBEAT_STALE


def note_notification_heartbeat(*, listener_access: str, slack_source_detected: bool) -> None:
    _state.last_heartbeat_at = utc_now()
    _state.listener_access = listener_access
    _state.permission_allowed = listener_access == "allowed"
    _state.slack_source_detected = slack_source_detected
    _state.helper_connected = True


def notification_health(settings: Settings | None = None) -> SlackNotificationHealth:
    cfg = settings or get_settings()
    refresh_notification_connection()
    enabled = slack_notification_capture_enabled(cfg)
    token = resolve_slack_notification_token(cfg)
    return SlackNotificationHealth(
        enabled=enabled,
        helper_connected=_state.helper_connected if enabled else False,
        permission_allowed=_state.permission_allowed if enabled else False,
        slack_source_detected=_state.slack_source_detected if enabled else False,
        last_heartbeat_at=_state.last_heartbeat_at if enabled else None,
        last_event_at=_state.last_event_at if enabled else None,
        token_configured=bool(token),
    )


def extra_source_ids(settings: Settings | None = None) -> tuple[str, ...]:
    cfg = settings or get_settings()
    return configured_source_ids(cfg.slack_notification_source_ids)


def _timestamp_for(event: SlackNotificationEvent) -> datetime:
    parsed = parse_created_at(event.received_at)
    return parsed or utc_now()


def _should_skip(event: SlackNotificationEvent) -> bool:
    if event.mapping_confidence == "low":
        return True
    if is_aggregate_text(event.text, event.conversation_hint, event.sender_name):
        return True
    if not (event.text or "").strip():
        return True
    return False


def _chat_external_id(event: SlackNotificationEvent) -> str:
    hint = event.conversation_hint or event.sender_name or "unknown"
    kind = "channel" if event.conversation_kind == "channel" else "direct"
    return notification_chat_id(kind=kind, hint=hint)


def _safe_raw(event: SlackNotificationEvent) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "notification_capture",
        "ingestion_source": "slack_notification",
        "notification_truncated": bool(event.is_truncated),
        "timestamp_kind": "windows_notification",
        "mapping_confidence": event.mapping_confidence,
    }
    if event.thread_hint:
        payload["thread_hint"] = event.thread_hint
    if event.conversation_hint:
        payload["conversation_hint"] = event.conversation_hint
    return {key: value for key, value in payload.items() if key in SAFE_RAW_KEYS}


def ingest_slack_notification_event(
    session: Session,
    event: SlackNotificationEvent,
) -> SlackSyncResult:
    """Persist one normalized Slack Desktop notification. Never calls AI. Never talks to Slack."""
    result = SlackSyncResult()
    if _should_skip(event):
        result.messages_skipped = 1
        logger.info("slack notification skipped reason=aggregate_or_low_confidence")
        return result
    ingestion = MessageIngestionService(session)
    contacts_before = session.scalar(select(func.count()).select_from(Contact)) or 0
    chat_external_id = _chat_external_id(event)
    chat_type = CHAT_TYPES.get(event.conversation_kind, ChatType.DIRECT)
    chat_name = event.conversation_hint or event.sender_name or chat_external_id
    chat, chat_created = ingestion.ingest_chat(
        UnifiedChat(
            platform=Platform.SLACK,
            external_id=chat_external_id,
            name=chat_name,
            chat_type=chat_type,
        )
    )
    result.chats_seen = 1
    if chat_created:
        result.chats_created = 1
    _ = chat
    unified = UnifiedMessage(
        platform=Platform.SLACK,
        external_id=event.notification_external_id,
        chat_id=chat_external_id,
        chat_name=chat_name,
        sender_id=None,
        sender_name=event.sender_name,
        text=event.text.strip()[:MAX_TEXT],
        timestamp=_timestamp_for(event),
        direction=MessageDirection.INCOMING,
        direction_source=DirectionSource.NOTIFICATION,
        attach_contact=False,
        raw_data=_safe_raw(event),
        thread_external_id=None,
    )
    stored, created = ingestion.ingest_message(unified)
    result.messages_seen = 1
    if created:
        result.messages_created = 1
    else:
        result.messages_existing = 1
        if ingestion.message_updated:
            result.messages_updated = 1
    _ = stored
    contacts_after = session.scalar(select(func.count()).select_from(Contact)) or 0
    result.contacts_created = max(0, contacts_after - contacts_before)
    _state.last_event_at = utc_now()
    _state.slack_source_detected = True
    runtime = get_sync_runtime()
    if inbox_changed(result):
        runtime.inbox_generation += 1
    logger.info(
        "slack notification ingest chats_created=%s messages_created=%s messages_existing=%s",
        result.chats_created,
        result.messages_created,
        result.messages_existing,
    )
    return result
