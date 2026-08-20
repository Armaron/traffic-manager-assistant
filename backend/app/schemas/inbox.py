from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums import ChatType, ConversationStatus, Platform, Priority


class ChatStatusUpdate(BaseModel):
    status: ConversationStatus


class ChatSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: Platform
    name: str
    chat_type: ChatType
    status: ConversationStatus
    last_message_at: datetime | None
    last_message_preview: str | None
    last_sender_name: str | None
    message_count: int
    ai_priority: Priority | None = None
    ai_needs_reply: bool | None = None
    ai_needs_igor: bool | None = None


class SeedResult(BaseModel):
    chats_created: int = 0
    chats_existing: int = 0
    messages_created: int = 0
    messages_existing: int = 0
    chats_total: int = 0
    messages_total: int = 0


class AnalyzeAllResult(BaseModel):
    analyzed: int = 0
    existing: int = 0
    skipped: int = 0


class TypeXHealth(BaseModel):
    mode: str
    connected: bool
    discovery_complete: bool = False
    configured: bool = False
    sync_ready: bool = False
    sync_mode: str | None = None
    warning_code: str | None = None
    sync_block_reason: str | None = None
    available_tools_count: int = 0
    allowed_read_tools_count: int = 0
    missing_required_tools: list[str] = []


class TypeXSyncResult(BaseModel):
    chats_seen: int = 0
    chats_created: int = 0
    messages_seen: int = 0
    messages_created: int = 0
    messages_existing: int = 0
    messages_skipped: int = 0
    messages_unknown_direction: int = 0
    messages_incoming: int = 0
    messages_outgoing: int = 0
    files_seen: int = 0
    files_saved: int = 0
    files_skipped: int = 0
    media_without_file: int = 0
    contacts_created: int = 0


class TelegramHealth(BaseModel):
    mode: str
    configured: bool = False
    connected: bool = False
    authorized: bool = False
    sync_ready: bool = False
    missing_configuration: list[str] = []


class TelegramSyncResult(BaseModel):
    chats_seen: int = 0
    chats_created: int = 0
    messages_seen: int = 0
    messages_created: int = 0
    messages_existing: int = 0
    messages_skipped: int = 0
    contacts_created: int = 0
    media_seen: int = 0
    media_downloaded: int = 0
    media_failed: int = 0
    media_skipped_size: int = 0
    media_already_stored: int = 0


class SlackHealth(BaseModel):
    mode: str
    configured: bool = False
    authenticated: bool = False
    socket_configured: bool = False
    socket_connected: bool = False
    sync_ready: bool = False
    browser_connected: bool = False
    last_heartbeat_at: datetime | None = None
    workspace_present: bool = False


class SlackSyncResult(BaseModel):
    chats_seen: int = 0
    chats_created: int = 0
    messages_seen: int = 0
    messages_created: int = 0
    messages_existing: int = 0
    messages_skipped: int = 0
    contacts_created: int = 0
    threads_seen: int = 0
    files_seen: int = 0
    files_downloaded: int = 0
    files_existing: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    media_downloaded: int = 0
    messages_updated: int = 0


