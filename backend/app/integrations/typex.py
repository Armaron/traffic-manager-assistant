"""TypeX adapter.

Real access uses TypeX Desktop MCP only, via configurable TYPEX_MCP_URL.
The default http://127.0.0.1:52222/mcp/ is a fallback — verify it against
the installed TypeX version before TYPEX_MODE=real.

This adapter is READ-ONLY. It calls only exact configured tool names.
Send/edit/delete/reaction/archive/mute/block tools are never wrapped.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.enums import Platform
from app.integrations.base import MessengerAdapter
from app.integrations.typex_errors import TypeXConfigurationError, TypeXToolUnavailableError
from app.integrations.typex_mapping import (
    extract_list,
    map_chat,
    map_message,
    map_sender,
)
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import (
    MCPTool,
    clean_tool_name,
    limit_field,
    message_chat_id_field,
    sender_id_field,
)
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
            if self._client.tool_by_name(name) is None:
                raise TypeXToolUnavailableError("TypeX read operation failed")
        messages_tool = self._require_discovered(self._messages_tool)
        if message_chat_id_field(messages_tool) is None:
            raise TypeXToolUnavailableError("TypeX read operation failed")

    async def get_chats(self) -> list[UnifiedChat]:
        tool = await self._require_configured_tool(self._chats_tool)
        payload = await self._client.call_tool(tool.name, _limit_args(tool, self._chat_limit))
        chats: list[UnifiedChat] = []
        for item in extract_list(payload):
            mapped = map_chat(item)
            if mapped is not None:
                chats.append(mapped)
            if len(chats) >= self._chat_limit:
                break
        return chats

    async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
        self.last_messages_seen = 0
        self.last_messages_skipped = 0
        tool = await self._require_configured_tool(self._messages_tool)
        chat_field = message_chat_id_field(tool)
        if chat_field is None:
            raise TypeXToolUnavailableError("TypeX read operation failed")
        await self._load_current_user()
        chat = UnifiedChat(platform=Platform.TYPEX, external_id=chat_id, name=chat_id)
        payload = await self._client.call_tool(tool.name, _message_args(tool, chat_id, self._message_limit))
        messages: list[UnifiedMessage] = []
        raw_items = extract_list(payload)
        self.last_messages_seen = len(raw_items)
        skipped = 0
        for item in raw_items:
            mapped = map_message(item, chat=chat, current_user_id=self._current_user_id)
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
        arguments = _sender_args(tool, sender_id)
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
        payload = await self._client.call_tool(tool.name, {})
        items = extract_list(payload)
        if not items and isinstance(payload, dict):
            items = [payload]
        if not items:
            return
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
        return tool


def configured_read_tool_names_from_adapter(adapter: TypeXAdapter) -> set[str]:
    names = {
        adapter._chats_tool,
        adapter._messages_tool,
        adapter._current_user_tool,
        adapter._sender_tool,
    }
    return {name for name in names if name}


def _limit_args(tool: MCPTool, limit: int) -> dict[str, Any]:
    field = limit_field(tool)
    return {field: limit} if field else {}


def _message_args(tool: MCPTool, chat_id: str, limit: int) -> dict[str, Any]:
    chat_field = message_chat_id_field(tool)
    if chat_field is None:
        raise TypeXToolUnavailableError("TypeX read operation failed")
    args: dict[str, Any] = {chat_field: chat_id}
    args.update(_limit_args(tool, limit))
    return args


def _sender_args(tool: MCPTool, sender_id: str) -> dict[str, Any]:
    field = sender_id_field(tool)
    return {field: sender_id} if field else {}
