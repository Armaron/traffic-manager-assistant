"""TypeX adapter.

Real access uses TypeX Desktop MCP only, via configurable TYPEX_MCP_URL.
The default http://127.0.0.1:52222/mcp/ is a fallback — verify it against
the installed TypeX version before TYPEX_MODE=real.

This adapter is READ-ONLY for chat/message tools.
Send/edit/delete/reaction/archive/mute/block/upload tools are never wrapped.
File save uses typex.download_chat_file only as local Save As into data/attachments.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings
from app.enums import AttachmentKind, MessageDirection, Platform
from app.integrations.base import MessengerAdapter
from app.integrations.typex_bindings import (
    build_chats_arguments,
    build_current_user_arguments,
    build_file_save_arguments,
    build_files_list_arguments,
    build_messages_arguments,
    build_sender_arguments,
    is_safely_scoped_files_list_tool,
    is_safely_scoped_messages_tool,
    sender_lookup_is_exact,
)
from app.integrations.typex_direction import (
    TypeXDirectionContext,
    TypeXIdentity,
    identity_from_get_me,
)
from app.integrations.typex_errors import TypeXConfigurationError, TypeXToolUnavailableError
from app.integrations.typex_mapping import (
    extract_list,
    map_chat,
    map_current_user,
    map_message,
    map_sender,
    normalize_typex_feed,
    normalize_typex_record,
)
from app.integrations.typex_files import map_downloadable_file
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import MCPTool, clean_tool_name, is_allowed_local_save_tool, is_write_tool
from app.integrations.typex_readiness import TypeXSyncReadiness, real_typex_sync_readiness
from app.integrations.typex_resolver import (
    CONVERSATION_RESOLVER_TOOL,
    ResolvedTypeXConversation,
    TypeXConversationResolver,
    normalize_display_name,
    typex_conversation_key,
)
from app.schemas.unified import UnifiedAttachment, UnifiedChat, UnifiedMessage, UnifiedSender
from app.services.attachment_storage import (
    MAX_ATTACHMENT_BYTES,
    attachments_root,
    content_type_for,
    discard_download_dir,
    is_within_attachments,
    kind_from_filename,
    normalized_filename,
    promote_to_content_path,
    sniff_media,
    storage_key_for,
    typex_chat_dir,
    typex_download_dir,
)


class TypeXAdapter(MessengerAdapter):
    platform = Platform.TYPEX

    def __init__(
        self,
        client: TypeXMCPClient,
        *,
        chats_tool: str | None,
        messages_tool: str | None,
        current_user_tool: str | None = None,
        sender_tool: str | None = None,
        files_list_tool: str | None = None,
        file_save_tool: str | None = None,
        chat_limit: int = 20,
        message_limit: int = 50,
    ) -> None:
        self._client = client
        self._chats_tool = clean_tool_name(chats_tool)
        self._messages_tool = clean_tool_name(messages_tool)
        self._current_user_tool = clean_tool_name(current_user_tool)
        self._sender_tool = clean_tool_name(sender_tool)
        self._files_list_tool = clean_tool_name(files_list_tool)
        self._file_save_tool = clean_tool_name(file_save_tool)
        self._chat_limit = chat_limit
        self._message_limit = message_limit
        self._current_user_id: str | None = None
        self._current_user_identity = TypeXIdentity()
        self._current_user_exact_name: str | None = None
        self._current_user_exact_names: set[str] = set()
        self._current_user_loaded = False
        self._chat_cache: dict[str, UnifiedChat] = {}
        self._conversation_by_id: dict[str, ResolvedTypeXConversation] = {}
        self._opaque_by_chat_id: dict[str, str] = {}
        self._resolver: TypeXConversationResolver | None = None
        self.last_messages_seen = 0
        self.last_messages_skipped = 0
        self.last_messages_unknown_direction = 0
        self.last_files_seen = 0
        self.last_files_saved = 0
        self.last_files_skipped = 0
        if self._chats_tool == "typex.list_folder_feeds":
            self._client.allow_internal_read_tool(CONVERSATION_RESOLVER_TOOL)
            self._resolver = TypeXConversationResolver(self._client)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TypeXAdapter:
        cfg = settings or get_settings()
        return cls(
            TypeXMCPClient.from_settings(cfg),
            chats_tool=cfg.typex_chats_tool,
            messages_tool=cfg.typex_messages_tool,
            current_user_tool=cfg.typex_current_user_tool,
            sender_tool=cfg.typex_sender_tool,
            files_list_tool=cfg.typex_files_list_tool,
            file_save_tool=cfg.typex_file_save_tool,
            chat_limit=cfg.typex_sync_chat_limit,
            message_limit=cfg.typex_sync_message_limit,
        )

    def is_configured(self) -> bool:
        return self._chats_tool is not None and self._messages_tool is not None

    def missing_required_bindings(self) -> list[str]:
        missing: list[str] = []
        if self._chats_tool is None:
            missing.append("TYPEX_CHATS_TOOL")
        if self._messages_tool is None:
            missing.append("TYPEX_MESSAGES_TOOL")
        return missing

    def sync_readiness(self) -> TypeXSyncReadiness:
        """Limited Sync is ready when configured. Direction may still be UNKNOWN."""
        return real_typex_sync_readiness(configured=self.is_configured())

    async def health_check(self) -> bool:
        return await self._client.health_check()

    async def ensure_ready_for_sync(self) -> None:
        """Fail closed before any chat/message read. No partial sync."""
        if not self.is_configured():
            raise TypeXConfigurationError("TypeX configuration required")
        await self._client.ensure_session()
        for name in configured_read_tool_names_from_adapter(self):
            tool = self._require_discovered(name)
            if is_write_tool(tool):
                raise TypeXToolUnavailableError("TypeX read operation failed")
        chats_tool = self._require_discovered(self._chats_tool)
        messages_tool = self._require_discovered(self._messages_tool)
        if not is_safely_scoped_messages_tool(messages_tool):
            raise TypeXToolUnavailableError("TypeX read operation failed")
        build_chats_arguments(chats_tool, self._chat_limit)
        build_messages_arguments(messages_tool, "scope-check", self._message_limit)
        if self._current_user_tool is not None:
            build_current_user_arguments(self._require_discovered(self._current_user_tool))
        if self._sender_tool is not None:
            sender_tool = self._require_discovered(self._sender_tool)
            if not sender_lookup_is_exact(sender_tool):
                raise TypeXToolUnavailableError("TypeX read operation failed")
            build_sender_arguments(sender_tool, "sender-check")
        if self._files_list_tool or self._file_save_tool:
            if not self._files_list_tool or not self._file_save_tool:
                raise TypeXToolUnavailableError("TypeX read operation failed")
            files_tool = self._require_discovered(self._files_list_tool)
            if not is_safely_scoped_files_list_tool(files_tool):
                raise TypeXToolUnavailableError("TypeX read operation failed")
            build_files_list_arguments(files_tool, "scope-check", self._message_limit)
            save_tool = self._require_local_save_tool(self._file_save_tool)
            build_file_save_arguments(
                save_tool,
                "scope-check",
                save_path=str(attachments_root()),
                file_ref="file-check",
            )
        if self._resolver is not None:
            resolver_tool = self._client.tool_by_name(CONVERSATION_RESOLVER_TOOL)
            if resolver_tool is None or is_write_tool(resolver_tool):
                raise TypeXToolUnavailableError("TypeX read operation failed")

    async def get_chats(self) -> list[UnifiedChat]:
        tool = await self._require_configured_tool(self._chats_tool)
        payload = await self._client.call_tool(tool.name, build_chats_arguments(tool, self._chat_limit))
        chats: list[UnifiedChat] = []
        for item in extract_list(payload):
            mapped = await self._map_listed_chat(item)
            if mapped is None:
                continue
            chats.append(mapped)
            if len(chats) >= self._chat_limit:
                break
        self._chat_cache = {}
        for chat in chats:
            self._chat_cache[chat.external_id] = chat
            opaque = self._opaque_by_chat_id.get(chat.external_id)
            if opaque:
                self._chat_cache[opaque] = chat
        return chats

    async def _map_listed_chat(self, item: dict) -> UnifiedChat | None:
        handle = None
        resolved = None
        if self._resolver is not None:
            resolved = await self._resolver.resolve(item)
            if resolved is None:
                return None
            handle = resolved.opaque_ref
            item = {**item, "opaque_ref": handle}
        mapped = map_chat(normalize_typex_feed(item))
        if mapped is None:
            return None
        if mapped.external_id == mapped.name:
            return None
        if handle:
            stable = typex_conversation_key(mapped.chat_type, mapped.name)
            if stable is None:
                return None
            mapped = mapped.model_copy(update={"external_id": stable})
            self._opaque_by_chat_id[stable] = handle
            self._opaque_by_chat_id[handle] = handle
            if resolved is not None:
                self._conversation_by_id[stable] = resolved
                self._conversation_by_id[handle] = resolved
        return mapped

    async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
        self.last_messages_seen = 0
        self.last_messages_skipped = 0
        self.last_messages_unknown_direction = 0
        tool = await self._require_configured_tool(self._messages_tool)
        if not is_safely_scoped_messages_tool(tool):
            raise TypeXToolUnavailableError("TypeX read operation failed")
        await self._load_current_user()
        chat = self._chat_cache.get(chat_id) or UnifiedChat(
            platform=Platform.TYPEX,
            external_id=chat_id,
            name=chat_id,
        )
        payload = await self._client.call_tool(
            tool.name,
            build_messages_arguments(tool, self._opaque_ref_for(chat_id), self._message_limit),
        )
        messages: list[UnifiedMessage] = []
        raw_items = extract_list(payload)
        self.last_messages_seen = len(raw_items)
        skipped = 0
        unknown = 0
        direction_context = self._direction_context_for(chat)
        for item in raw_items:
            mapped = map_message(
                normalize_typex_record(item),
                chat=chat,
                current_user_id=self._current_user_id,
                direction_context=direction_context,
            )
            if mapped is None:
                skipped += 1
                continue
            if mapped.direction == MessageDirection.UNKNOWN:
                unknown += 1
            messages.append(mapped)
        self.last_messages_skipped = skipped
        self.last_messages_unknown_direction = unknown
        messages.sort(key=lambda item: item.timestamp)
        return messages[-self._message_limit :]

    async def get_recent_messages(self, limit: int = 50) -> list[UnifiedMessage]:
        chats = await self.get_chats()
        collected: list[UnifiedMessage] = []
        for chat in chats:
            collected.extend(await self.get_messages(chat.external_id))
        collected.sort(key=lambda item: item.timestamp, reverse=True)
        return collected[:limit]

    async def get_sender(self, sender_id: str) -> UnifiedSender | None:
        if self._sender_tool is None:
            return None
        tool = await self._require_configured_tool(self._sender_tool)
        arguments = build_sender_arguments(tool, sender_id)
        payload = await self._client.call_tool(tool.name, arguments)
        items = extract_list(payload)
        if not items and isinstance(payload, dict):
            items = [payload]
        for item in items:
            mapped = map_sender(item)
            if mapped is not None:
                return mapped
        return None

    async def get_chat_files(self, chat_id: str) -> list[UnifiedAttachment]:
        self.last_files_seen = 0
        self.last_files_saved = 0
        self.last_files_skipped = 0
        if self._files_list_tool is None or self._file_save_tool is None:
            return []
        tool = await self._require_configured_tool(self._files_list_tool)
        if not is_safely_scoped_files_list_tool(tool):
            raise TypeXToolUnavailableError("TypeX read operation failed")
        payload = await self._client.call_tool(
            tool.name,
            build_files_list_arguments(tool, self._opaque_ref_for(chat_id), self._message_limit),
        )
        items = extract_list(payload)
        self.last_files_seen = len(items)
        mapped_items: list[UnifiedAttachment] = []
        for item in items:
            mapped = map_downloadable_file(item)
            if mapped is None:
                self.last_files_skipped += 1
                continue
            mapped_items.append(mapped)
            if len(mapped_items) >= self._message_limit:
                break
        saved: list[UnifiedAttachment] = []
        for item in mapped_items:
            stored = await self._download_media(
                chat_id,
                item.file_ref,
                item,
                file_ref=item.file_ref,
            )
            if stored is None:
                self.last_files_skipped += 1
                continue
            self.last_files_saved += 1
            saved.append(stored)
        return saved

    async def download_message_media(
        self,
        chat_id: str,
        message_ref: str,
        *,
        kind: AttachmentKind = AttachmentKind.FILE,
    ) -> UnifiedAttachment | None:
        """Fallback path: TypeX can serve media by message_ref when no file_ref is listed."""
        if self._file_save_tool is None or not message_ref:
            return None
        item = UnifiedAttachment(
            file_ref=message_ref,
            message_external_id=message_ref,
            filename="media",
            kind=kind,
        )
        return await self._download_media(chat_id, message_ref, item, message_ref=message_ref)

    async def _download_media(
        self,
        chat_id: str,
        ref: str,
        item: UnifiedAttachment,
        *,
        file_ref: str | None = None,
        message_ref: str | None = None,
    ) -> UnifiedAttachment | None:
        tool = self._require_local_save_tool(self._file_save_tool)
        await self._client.ensure_session()
        folder = typex_download_dir(chat_id, ref)
        if not is_within_attachments(folder):
            return None
        try:
            payload = await self._client.call_tool(
                tool.name,
                build_file_save_arguments(
                    tool,
                    self._opaque_ref_for(chat_id),
                    save_path=str(folder),
                    file_ref=file_ref,
                    file_name=item.filename if file_ref else None,
                    message_ref=message_ref,
                ),
            )
            stored = _resolved_saved_path(payload, folder)
            if stored is None:
                return None
            size = stored.stat().st_size
            if size <= 0 or size > MAX_ATTACHMENT_BYTES:
                return None
            sniffed = sniff_media(stored)
            filename = normalized_filename(stored.name, sniffed[1]) if sniffed else stored.name
            promoted = promote_to_content_path(stored, filename, typex_chat_dir(chat_id))
            if promoted is None:
                return None
            key = storage_key_for(promoted)
            if key is None:
                return None
            kind = kind_from_filename(filename, item.kind)
            return item.model_copy(
                update={
                    "filename": filename,
                    "kind": kind,
                    "content_type": sniffed[0] if sniffed else content_type_for(filename, kind),
                    "storage_key": key,
                    "byte_size": size,
                }
            )
        finally:
            discard_download_dir(folder)

    def _require_local_save_tool(self, name: str | None) -> MCPTool:
        if name is None:
            raise TypeXConfigurationError("TypeX configuration required")
        tool = self._client.tool_by_name(name)
        if tool is None or not is_allowed_local_save_tool(tool):
            raise TypeXToolUnavailableError("TypeX read operation failed")
        return tool

    @property
    def current_user_exact_name(self) -> str | None:
        return self._current_user_exact_name

    @property
    def self_display_names(self) -> tuple[str, ...]:
        return tuple(self._current_user_exact_names)

    def _remember_self_name(self, value: str | None) -> None:
        name = normalize_display_name(value)
        if not name:
            return
        self._current_user_exact_names.add(name)
        self._current_user_exact_name = name

    async def _load_current_user(self) -> None:
        if self._current_user_loaded:
            return
        self._current_user_loaded = True
        self._remember_self_name(get_settings().typex_self_display_name)
        if self._current_user_tool is None:
            return
        tool = await self._require_configured_tool(self._current_user_tool)
        payload = await self._client.call_tool(tool.name, build_current_user_arguments(tool))
        self._current_user_identity = identity_from_get_me(payload)
        mapped = map_current_user(payload)
        if mapped is None:
            items = extract_list(payload)
            if not items and isinstance(payload, dict):
                items = [payload]
            if items:
                mapped = map_sender(items[0])
        if mapped is not None:
            self._current_user_id = mapped.external_id
            self._remember_self_name(mapped.name)
        if isinstance(payload, dict):
            nested = payload.get("me") or payload.get("user") or payload.get("profile")
            if isinstance(nested, dict):
                self._remember_self_name(nested.get("name"))
            else:
                self._remember_self_name(payload.get("name"))

    def _opaque_ref_for(self, chat_id: str) -> str:
        return self._opaque_by_chat_id.get(chat_id) or chat_id

    def _direction_context_for(self, chat: UnifiedChat) -> TypeXDirectionContext:
        resolved = self._conversation_by_id.get(chat.external_id)
        return TypeXDirectionContext(
            chat_type=resolved.chat_type if resolved is not None else chat.chat_type,
            current_user=self._current_user_identity,
            counterpart=resolved.counterpart_identity if resolved is not None else None,
            current_user_exact_name=self._current_user_exact_name,
            current_user_exact_names=tuple(self._current_user_exact_names),
            counterpart_exact_name=resolved.counterpart_exact_name if resolved is not None else None,
        )

    async def _require_configured_tool(self, name: str | None) -> MCPTool:
        if name is None:
            raise TypeXConfigurationError("TypeX configuration required")
        await self._client.ensure_session()
        return self._require_discovered(name)

    def _require_discovered(self, name: str | None) -> MCPTool:
        if name is None:
            raise TypeXConfigurationError("TypeX configuration required")
        tool = self._client.tool_by_name(name)
        if tool is None:
            raise TypeXToolUnavailableError("TypeX read operation failed")
        if is_write_tool(tool):
            raise TypeXToolUnavailableError("TypeX read operation failed")
        return tool


def configured_read_tool_names_from_adapter(adapter: TypeXAdapter) -> set[str]:
    names = {
        adapter._chats_tool,
        adapter._messages_tool,
        adapter._current_user_tool,
        adapter._sender_tool,
        adapter._files_list_tool,
    }
    return {name for name in names if name}


def _resolved_saved_path(payload: object, folder: Path) -> Path | None:
    """TypeX picks the file name itself, so trust saved_path and fall back to the folder."""
    if isinstance(payload, dict):
        for key in ("saved_path", "save_path", "path", "file_path", "local_path"):
            raw = payload.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw)
            if is_within_attachments(path) and path.is_file():
                return path
    if not folder.is_dir():
        return None
    files = [item for item in folder.rglob("*") if item.is_file()]
    return files[0] if len(files) == 1 else None
