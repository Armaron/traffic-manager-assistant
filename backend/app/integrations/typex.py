"""TypeX adapter.

Real access uses official TypeX Desktop MCP only:
enable MCP in TypeX Desktop, then connect to the configured TYPEX_MCP_URL
(default http://127.0.0.1:52222/mcp/).

This adapter is READ-ONLY. Send/edit/delete/reaction tools are never called.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.enums import Platform
from app.integrations.base import MessengerAdapter
from app.integrations.typex_errors import TypeXToolUnavailableError
from app.integrations.typex_mapping import (
    extract_list,
    map_chat,
    map_message,
    map_sender,
)
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import MCPTool, pick_tool
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender


class TypeXAdapter(MessengerAdapter):
    platform = Platform.TYPEX

    def __init__(
        self,
        client: TypeXMCPClient,
        *,
        chat_limit: int = 20,
        message_limit: int = 50,
    ) -> None:
        self._client = client
        self._chat_limit = chat_limit
        self._message_limit = message_limit
        self._current_user_id: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TypeXAdapter:
        cfg = settings or get_settings()
        return cls(
            TypeXMCPClient.from_settings(cfg),
            chat_limit=cfg.typex_sync_chat_limit,
            message_limit=cfg.typex_sync_message_limit,
        )

    async def health_check(self) -> bool:
        return await self._client.health_check()

    async def get_chats(self) -> list[UnifiedChat]:
        await self._client.ensure_session()
        tool = pick_tool(
            self._client.discovered_tools,
            "conversation",
            "chat",
            "group",
            "search",
        )
        if tool is None:
            raise TypeXToolUnavailableError("TypeX read operation failed")
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
        await self._client.ensure_session()
        await self._load_current_user()
        tool = pick_tool(
            self._client.discovered_tools,
            "message",
            "history",
            "search",
        )
        if tool is None:
            raise TypeXToolUnavailableError("TypeX read operation failed")
        chat = UnifiedChat(platform=Platform.TYPEX, external_id=chat_id, name=chat_id)
        arguments = _message_args(tool, chat_id, self._message_limit)
        payload = await self._client.call_tool(tool.name, arguments)
        messages: list[UnifiedMessage] = []
        for item in extract_list(payload):
            mapped = map_message(item, chat=chat, current_user_id=self._current_user_id)
            if mapped is not None:
                messages.append(mapped)
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
        await self._client.ensure_session()
        tool = pick_tool(self._client.discovered_tools, "user", "contact", "profile")
        if tool is None:
            return None
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
        if self._current_user_id:
            return
        tool = pick_tool(self._client.discovered_tools, "current user", "current_user", "me", "account")
        if tool is None:
            return
        payload = await self._client.call_tool(tool.name, {})
        items = extract_list(payload)
        if not items and isinstance(payload, dict):
            items = [payload]
        if not items:
            return
        mapped = map_sender(items[0])
        if mapped is not None:
            self._current_user_id = mapped.external_id


def _schema_props(tool: MCPTool) -> dict[str, Any]:
    schema = tool.input_schema or {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _limit_args(tool: MCPTool, limit: int) -> dict[str, Any]:
    props = _schema_props(tool)
    args: dict[str, Any] = {}
    for key in ("limit", "page_size", "pageSize", "count", "max_results", "size"):
        if key in props:
            args[key] = limit
            break
    return args


def _message_args(tool: MCPTool, chat_id: str, limit: int) -> dict[str, Any]:
    props = _schema_props(tool)
    args = _limit_args(tool, limit)
    for key in ("chat_id", "conversation_id", "group_id", "target_id", "id"):
        if key in props:
            args[key] = chat_id
            break
    return args


def _sender_args(tool: MCPTool, sender_id: str) -> dict[str, Any]:
    props = _schema_props(tool)
    for key in ("user_id", "sender_id", "id", "uid"):
        if key in props:
            return {key: sender_id}
    return {}
