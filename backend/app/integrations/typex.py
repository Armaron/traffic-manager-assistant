"""TypeX adapter.

Real access uses TypeX Desktop MCP only, via configurable TYPEX_MCP_URL.
The default http://127.0.0.1:52222/mcp/ is a fallback — verify it against
the installed TypeX version before TYPEX_MODE=real.

This adapter is READ-ONLY. It calls only exact configured tool names that
are discovered and not classified as write/mutation.
Send/edit/delete/reaction/archive/mute/block tools are never wrapped.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.enums import Platform
from app.integrations.base import MessengerAdapter
from app.integrations.typex_bindings import (
    build_chats_arguments,
    build_current_user_arguments,
    build_messages_arguments,
    build_sender_arguments,
    is_safely_scoped_messages_tool,
    sender_lookup_is_exact,
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
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import MCPTool, clean_tool_name, is_write_tool
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender


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
        chat_limit: int = 20,
        message_limit: int = 50,
    ) -> None:
        self._client = client
        self._chats_tool = clean_tool_name(chats_tool)
        self._messages_tool = clean_tool_name(messages_tool)
        self._current_user_tool = clean_tool_name(current_user_tool)
        self._sender_tool = clean_tool_name(sender_tool)
        self._chat_limit = chat_limit
        self._message_limit = message_limit
        self._current_user_id: str | None = None
        self._chat_cache: dict[str, UnifiedChat] = {}
        self.last_messages_seen = 0
        self.last_messages_skipped = 0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TypeXAdapter:
        cfg = settings or get_settings()
        return cls(
            TypeXMCPClient.from_settings(cfg),
            chats_tool=cfg.typex_chats_tool,
            messages_tool=cfg.typex_messages_tool,
            current_user_tool=cfg.typex_current_user_tool,
            sender_tool=cfg.typex_sender_tool,
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

    async def get_chats(self) -> list[UnifiedChat]:
        tool = await self._require_configured_tool(self._chats_tool)
        payload = await self._client.call_tool(tool.name, build_chats_arguments(tool, self._chat_limit))
        chats: list[UnifiedChat] = []
        for item in extract_list(payload):
            mapped = map_chat(normalize_typex_feed(item))
            if mapped is not None:
                chats.append(mapped)
            if len(chats) >= self._chat_limit:
                break
        self._chat_cache = {chat.external_id: chat for chat in chats}
        return chats

    async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
        self.last_messages_seen = 0
        self.last_messages_skipped = 0
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
            build_messages_arguments(tool, chat_id, self._message_limit),
        )
        messages: list[UnifiedMessage] = []
        raw_items = extract_list(payload)
        self.last_messages_seen = len(raw_items)
        skipped = 0
        for item in raw_items:
            mapped = map_message(
                normalize_typex_record(item),
                chat=chat,
                current_user_id=self._current_user_id,
            )
            if mapped is None:
                skipped += 1
                continue
            messages.append(mapped)
        self.last_messages_skipped = skipped
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

    async def _load_current_user(self) -> None:
        if self._current_user_id or self._current_user_tool is None:
            return
        tool = await self._require_configured_tool(self._current_user_tool)
        payload = await self._client.call_tool(tool.name, build_current_user_arguments(tool))
        mapped = map_current_user(payload)
        if mapped is None:
            items = extract_list(payload)
            if not items and isinstance(payload, dict):
                items = [payload]
            if items:
                mapped = map_sender(items[0])
        if mapped is not None:
            self._current_user_id = mapped.external_id

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
    }
    return {name for name in names if name}
