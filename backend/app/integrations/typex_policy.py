"""Read-only TypeX MCP policy.

Live tool names are taken from MCP discovery, never from a guessed catalog.
Write-capable tools are denied even if TypeX Desktop exposes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None

    @property
    def blob(self) -> str:
        return f"{self.name} {self.description}".lower().replace("-", "_")


def is_write_tool(tool: MCPTool) -> bool:
    blob = tool.blob
    return any(marker in blob for marker in WRITE_MARKERS)


def is_read_tool(tool: MCPTool) -> bool:
    if is_write_tool(tool):
        return False
    blob = tool.blob
    return any(marker in blob for marker in READ_MARKERS)


def allowed_read_tools(tools: list[MCPTool]) -> list[MCPTool]:
    return [tool for tool in tools if is_read_tool(tool)]


def pick_tool(tools: list[MCPTool], *needles: str) -> MCPTool | None:
    allowed = allowed_read_tools(tools)
    for needle in needles:
        token = needle.lower().replace("-", "_")
        for tool in allowed:
            if _matches_needle(tool, token):
                return tool
    return None


def _matches_needle(tool: MCPTool, token: str) -> bool:
    blob = tool.blob
    if " " in token:
        return token in blob
    parts = set(blob.replace("/", " ").split())
    if token in parts:
        return True
    return len(token) >= 4 and token in blob
