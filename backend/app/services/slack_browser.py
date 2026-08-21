"""Local Slack Browser Reader ingest. No Slack SDK, tokens, or writes."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, Settings, get_settings
from app.enums import ChatType, DirectionSource, MessageDirection, Platform
from app.integrations.slack_dom_parser import (
    clean_sender_name,
    is_noise_text,
    is_slack_ts,
    strip_message_chrome,
)
from app.integrations.slack_mapping import TOMBSTONE_TEXT, slack_ts_to_datetime
from app.integrations.slack_self import apply_slack_self_outgoing, is_slack_self_name
from app.models import Contact
from app.schemas.inbox import SlackSyncResult
from app.schemas.slack_browser import SlackBrowserEventsPayload, SlackBrowserMessage
from app.schemas.unified import UnifiedChat, UnifiedMessage
from app.services.message_ingestion import MessageIngestionService
from app.services.sync_runtime import SyncPlatform, get_sync_runtime
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

TOKEN_HEADER = "X-CAS-Slack-Browser-Token"
TOKEN_FILE = DATA_DIR / "slack_browser_token"
HEARTBEAT_STALE = timedelta(seconds=45)
MAX_TEXT = 8000
SAFE_RAW_KEYS = frozenset({"source", "browser_fallback_id", "deleted", "attachment_placeholder"})

CHAT_TYPES = {
    "direct": ChatType.DIRECT,
    "group": ChatType.GROUP,
    "channel": ChatType.CHANNEL,
}


def slack_browser_mode(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return (cfg.slack_mode or "").strip().lower() == "browser"


def resolve_slack_browser_token(settings: Settings | None = None) -> str | None:
    cfg = settings or get_settings()
    env_token = (cfg.slack_browser_local_token or "").strip()
    if env_token:
        return env_token
    if TOKEN_FILE.is_file():
        stored = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    return None


def ensure_slack_browser_token(settings: Settings | None = None) -> str | None:
    """Create a local app token for the extension. This is not a Slack credential."""
    cfg = settings or get_settings()
    existing = resolve_slack_browser_token(cfg)
    if existing:
        return existing
    if not slack_browser_mode(cfg):
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    logger.info("slack browser local token stored under data/")
    return token


def token_matches(provided: str, settings: Settings | None = None) -> bool:
    expected = resolve_slack_browser_token(settings)
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided, expected)


def refresh_browser_connection(now: datetime | None = None) -> None:
    state = get_sync_runtime().state(SyncPlatform.SLACK)
    moment = now or utc_now()
    last = state.last_heartbeat_at
    if last is None:
        state.browser_connected = False
        return
    if last.tzinfo is None:
        last = last.replace(tzinfo=moment.tzinfo)
    state.browser_connected = (moment - last) <= HEARTBEAT_STALE


def note_browser_heartbeat(*, workspace_present: bool) -> None:
    runtime = get_sync_runtime()
    state = runtime.state(SyncPlatform.SLACK)
    state.last_heartbeat_at = utc_now()
    state.workspace_present = workspace_present
    state.browser_connected = True
    state.ready = True


def _parse_timestamp(value: str) -> datetime:
    text = value.strip()
    if is_slack_ts(text):
        return slack_ts_to_datetime(text)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return utc_now()
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=utc_now().tzinfo)
    return parsed


def _direction(message: SlackBrowserMessage) -> tuple[MessageDirection, DirectionSource]:
    if message.direction == "outgoing":
        source = DirectionSource.STABLE_ID if message.sender_external_id else DirectionSource.NATIVE
        return MessageDirection.OUTGOING, source
    if is_slack_self_name(message.sender_name):
        return MessageDirection.OUTGOING, DirectionSource.PROFILE_NAME
    if message.direction == "incoming":
        source = DirectionSource.STABLE_ID if message.sender_external_id else DirectionSource.NATIVE
        return MessageDirection.INCOMING, source
    return MessageDirection.UNKNOWN, DirectionSource.UNKNOWN


def _safe_raw(message: SlackBrowserMessage) -> dict[str, object]:
    payload: dict[str, object] = {"source": "browser"}
    if message.browser_fallback_id:
        payload["browser_fallback_id"] = True
    if message.deleted:
        payload["deleted"] = True
    if message.attachment_placeholder:
        payload["attachment_placeholder"] = message.attachment_placeholder
    return {key: value for key, value in payload.items() if key in SAFE_RAW_KEYS or key == "source"}


def _text_for(message: SlackBrowserMessage) -> str:
    sender = clean_sender_name(message.sender_name)
    text = strip_message_chrome(message.text or "", sender)
    if message.deleted:
        return TOMBSTONE_TEXT
    if message.attachment_placeholder == "image" and not text:
        return "[Image]"
    if message.attachment_placeholder == "file" and not text:
        return "[File]"
    return text[:MAX_TEXT]


def _should_skip_browser_message(message: SlackBrowserMessage) -> bool:
    if message.deleted:
        return False
    if message.attachment_placeholder:
        return False
    return is_noise_text(_text_for(message))


def ingest_slack_browser_events(
    session: Session,
    payload: SlackBrowserEventsPayload,
) -> SlackSyncResult:
    """Persist normalized browser messages. Never calls AI. Never talks to Slack."""
    ingestion = MessageIngestionService(session)
    result = SlackSyncResult()
    contacts_before = session.scalar(select(func.count()).select_from(Contact)) or 0
    conversation = payload.conversation
    kept_messages = [item for item in payload.messages if not _should_skip_browser_message(item)]
    if not kept_messages:
        logger.info("slack_browser ingest skipped empty or noise-only payload")
        note_browser_heartbeat(workspace_present=True)
        return result
    chat_type = CHAT_TYPES.get(conversation.type, ChatType.UNKNOWN)
    chat, chat_created = ingestion.ingest_chat(
        UnifiedChat(
            platform=Platform.SLACK,
            external_id=conversation.external_id,
            name=conversation.name or conversation.external_id,
            chat_type=chat_type,
        )
    )
    result.chats_seen = 1
    if chat_created:
        result.chats_created = 1
    _ = chat
    for item in kept_messages:
        direction, source = _direction(item)
        unified = UnifiedMessage(
            platform=Platform.SLACK,
            external_id=item.external_id,
            chat_id=conversation.external_id,
            chat_name=conversation.name or conversation.external_id,
            sender_id=item.sender_external_id,
            sender_name=clean_sender_name(item.sender_name),
            text=_text_for(item),
            timestamp=_parse_timestamp(item.timestamp),
            direction=direction,
            direction_source=source,
            attach_contact=direction == MessageDirection.INCOMING and bool(item.sender_external_id),
            raw_data=_safe_raw(item),
            thread_external_id=item.thread_external_id,
        )
        stored, created = ingestion.ingest_message(unified)
        result.messages_seen += 1
        if item.thread_external_id:
            result.threads_seen += 1
        if created:
            result.messages_created += 1
        else:
            result.messages_existing += 1
            if ingestion.message_updated:
                result.messages_updated += 1
        _ = stored
    updated_self = apply_slack_self_outgoing(session)
    if updated_self:
        get_sync_runtime().inbox_generation += 1
    contacts_after = session.scalar(select(func.count()).select_from(Contact)) or 0
    result.contacts_created = max(0, contacts_after - contacts_before)
    runtime = get_sync_runtime()
    note_browser_heartbeat(workspace_present=True)
    runtime.note_slack_event(result)
    logger.info(
        "slack_browser ingest chats_created=%s messages_created=%s messages_existing=%s messages_updated=%s",
        result.chats_created,
        result.messages_created,
        result.messages_existing,
        result.messages_updated,
    )
    return result
