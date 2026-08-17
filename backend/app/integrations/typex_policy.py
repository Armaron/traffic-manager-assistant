"""TypeX MCP policy.

Runtime authorization is exact configured tool names only.
Unknown / unconfigured tool = deny.

Keyword classification is diagnostics-only (discovery report, warnings).
It must never grant call permission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.config import Settings

# Diagnostics only. Never used to authorize a tools/call.
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
)

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

MESSAGE_CHAT_ID_FIELDS = ("chat_id", "conversation_id", "group_id", "target_id", "id")
LIMIT_FIELDS = ("limit", "page_size", "pageSize", "count", "max_results", "size")
SENDER_ID_FIELDS = ("user_id", "sender_id", "id", "uid")

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


def is_write_tool(tool: MCPTool) -> bool:
    """Diagnostic classification only."""
    blob = tool.blob
    return any(marker in blob for marker in WRITE_MARKERS)


def is_read_tool(tool: MCPTool) -> bool:
    """Diagnostic classification only. Never grants authorization."""
    if is_write_tool(tool):
        return False
    blob = tool.blob
    return any(marker in blob for marker in READ_MARKERS)


def diagnostic_kind(tool: MCPTool) -> DiagnosticKind:
    if is_write_tool(tool):
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


def message_chat_id_field(tool: MCPTool) -> str | None:
    fields = set(input_field_names(tool))
    for key in MESSAGE_CHAT_ID_FIELDS:
        if key in fields:
            return key
    return None


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
