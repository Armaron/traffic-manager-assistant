"""TypeX MCP policy.

Runtime authorization requires all of:
1. exact configured tool name
2. exact discovered tool
3. tool is not classified as write/mutation

Keyword classification never grants call permission.
WRITE_MARKERS remain a defense-in-depth deny layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.config import Settings

# Defense-in-depth deny layer. False positive DENY is acceptable.
WRITE_MARKERS = (
    "send",
    "reply",
    "edit",
    "delete",
    "remove",
    "create",
    "react",
    "reaction",
    "upload",
    "download",
    "invite",
    "kick",
    "forward",
    "reminder",
    "mark_read",
    "add_contact",
    "add-contact",
    "archive",
    "mute",
    "block",
    "pin",
    "leave",
    "unfollow",
    "update",
    "manage",
    "star",
)

_READ_NAME_PREFIXES = ("get", "list", "search", "find", "read", "fetch", "query")

READ_MARKERS = (
    "search",
    "list",
    "get",
    "read",
    "fetch",
    "find",
    "history",
    "message",
    "chat",
    "conversation",
    "group",
    "user",
    "contact",
    "profile",
    "mention",
    "me",
    "account",
    "current",
)

# Real TypeX Desktop MCP conversation handles, then generic/test fields.
# Bare "id" is omitted: it is ambiguous between message and conversation.
CONVERSATION_SCOPE_FIELDS = (
    "opaque_ref",
    "group_ref",
    "chat_ref",
    "feed_ref",
    "feed_id",
    "folder_feed_id",
    "chat_id",
    "conversation_id",
    "group_id",
    "target_id",
)
MESSAGE_CHAT_ID_FIELDS = CONVERSATION_SCOPE_FIELDS
LIMIT_FIELDS = ("limit", "page_size", "pageSize", "count", "max_results", "size")
SENDER_ID_FIELDS = ("user_id", "sender_id", "id", "uid")
ACCOUNT_WIDE_QUERY_FIELDS = ("query", "keyword", "q", "contact_name")

DiagnosticKind = Literal["read", "write", "unknown"]


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None

    @property
    def blob(self) -> str:
        return f"{self.name} {self.description}".lower().replace("-", "_")


def clean_tool_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def configured_read_tool_names(settings: Settings) -> set[str]:
    """Exact operator-configured allowlist. Blank names are ignored."""
    names = (
        settings.typex_chats_tool,
        settings.typex_messages_tool,
        settings.typex_current_user_tool,
        settings.typex_sender_tool,
    )
    return {item for item in (clean_tool_name(name) for name in names) if item}


def missing_required_tool_bindings(settings: Settings) -> list[str]:
    missing: list[str] = []
    if clean_tool_name(settings.typex_chats_tool) is None:
        missing.append("TYPEX_CHATS_TOOL")
    if clean_tool_name(settings.typex_messages_tool) is None:
        missing.append("TYPEX_MESSAGES_TOOL")
    return missing


def _normalized_tool_name(name: str) -> str:
    return name.lower().replace("-", "_")


def _short_tool_name(name: str) -> str:
    return _normalized_tool_name(name).rsplit(".", 1)[-1]


def _name_has_write_marker(name: str) -> bool:
    blob = _normalized_tool_name(name)
    return any(marker in blob for marker in WRITE_MARKERS)


def _blob_has_write_marker(tool: MCPTool) -> bool:
    return any(marker in tool.blob for marker in WRITE_MARKERS)


def _name_looks_like_read(name: str) -> bool:
    short = _short_tool_name(name)
    return any(short == prefix or short.startswith(f"{prefix}_") for prefix in _READ_NAME_PREFIXES)


def is_write_tool(tool: MCPTool) -> bool:
    """Runtime write/mutation deny. Name-first so description tokens cannot block get_me.

    Description markers remain defense-in-depth only when the tool name is not an
    obvious read verb. False positive DENY is acceptable.
    """
    if _name_has_write_marker(tool.name):
        return True
    if _name_looks_like_read(tool.name):
        return False
    return _blob_has_write_marker(tool)


def is_read_tool(tool: MCPTool) -> bool:
    """Diagnostic classification only. Never grants authorization."""
    if _blob_has_write_marker(tool):
        return False
    blob = tool.blob
    return any(marker in blob for marker in READ_MARKERS)


def diagnostic_kind(tool: MCPTool) -> DiagnosticKind:
    if _blob_has_write_marker(tool):
        return "write"
    if is_read_tool(tool):
        return "read"
    return "unknown"


def input_field_names(tool: MCPTool) -> list[str]:
    schema = tool.input_schema or {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    return [str(key) for key in props]


def required_field_names(tool: MCPTool) -> list[str]:
    schema = tool.input_schema or {}
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [str(item) for item in required if item]


def conversation_scope_field(tool: MCPTool) -> str | None:
    fields = set(input_field_names(tool))
    for key in CONVERSATION_SCOPE_FIELDS:
        if key in fields:
            return key
    return None


def message_chat_id_field(tool: MCPTool) -> str | None:
    return conversation_scope_field(tool)


def limit_field(tool: MCPTool) -> str | None:
    fields = set(input_field_names(tool))
    for key in LIMIT_FIELDS:
        if key in fields:
            return key
    return None


def sender_id_field(tool: MCPTool) -> str | None:
    fields = set(input_field_names(tool))
    for key in SENDER_ID_FIELDS:
        if key in fields:
            return key
    return None
