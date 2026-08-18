"""Deterministic TypeX role/schema argument construction.

Real tool name + validated inputSchema → arguments. No guessed values.
Unknown required fields fail closed. Account-wide message search is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.integrations.typex_errors import TypeXToolUnavailableError
from app.integrations.typex_policy import (
    ACCOUNT_WIDE_QUERY_FIELDS,
    MCPTool,
    conversation_scope_field,
    input_field_names,
    is_write_tool,
    limit_field,
    required_field_names,
    sender_id_field,
)

Role = Literal["chats", "messages", "current_user", "sender"]


@dataclass(frozen=True)
class TypeXToolBinding:
    tool_name: str
    role: Role
    conversation_scope_field: str | None = None
    limit_field: str | None = None


def _deny() -> None:
    raise TypeXToolUnavailableError("TypeX read operation failed")


def missing_unfillable_required(tool: MCPTool, provided: set[str]) -> list[str]:
    return [name for name in required_field_names(tool) if name not in provided]


def is_account_wide_messages_tool(tool: MCPTool) -> bool:
    """True when a MESSAGES role cannot be scoped to one conversation-like entity."""
    if conversation_scope_field(tool) is not None:
        return False
    return True


def is_safely_scoped_messages_tool(tool: MCPTool) -> bool:
    if is_write_tool(tool):
        return False
    return conversation_scope_field(tool) is not None


def sender_lookup_is_exact(tool: MCPTool) -> bool:
    """Fuzzy name search is not a safe sender-id lookup."""
    if is_write_tool(tool):
        return False
    if sender_id_field(tool) is None:
        return False
    required = set(required_field_names(tool))
    if "name" in required or "query" in required or "keyword" in required:
        return False
    return True


def binding_for(tool: MCPTool, role: Role) -> TypeXToolBinding:
    return TypeXToolBinding(
        tool_name=tool.name,
        role=role,
        conversation_scope_field=conversation_scope_field(tool) if role == "messages" else None,
        limit_field=limit_field(tool),
    )


def build_chats_arguments(tool: MCPTool, limit: int) -> dict[str, Any]:
    if is_write_tool(tool):
        _deny()
    args: dict[str, Any] = {}
    fields = set(input_field_names(tool))
    if "all_chats" in fields:
        args["all_chats"] = True
    field = limit_field(tool)
    if field:
        args[field] = limit
    if missing_unfillable_required(tool, set(args)):
        _deny()
    return args


def build_messages_arguments(tool: MCPTool, conversation_id: str, limit: int) -> dict[str, Any]:
    if is_write_tool(tool):
        _deny()
    if not conversation_id or is_account_wide_messages_tool(tool):
        _deny()
    scope = conversation_scope_field(tool)
    if scope is None:
        _deny()
    args: dict[str, Any] = {scope: conversation_id}
    field = limit_field(tool)
    if field:
        args[field] = limit
    if missing_unfillable_required(tool, set(args)):
        _deny()
    # Never add account-wide search fields, even when optional.
    for unsafe in ACCOUNT_WIDE_QUERY_FIELDS:
        args.pop(unsafe, None)
    return args


def build_current_user_arguments(tool: MCPTool) -> dict[str, Any]:
    if is_write_tool(tool):
        _deny()
    if missing_unfillable_required(tool, set()):
        _deny()
    return {}


def build_sender_arguments(tool: MCPTool, sender_id: str) -> dict[str, Any]:
    if is_write_tool(tool) or not sender_lookup_is_exact(tool):
        _deny()
    field = sender_id_field(tool)
    if field is None or not sender_id:
        _deny()
    args: dict[str, Any] = {field: sender_id}
    if missing_unfillable_required(tool, set(args)):
        _deny()
    return args


def is_safely_scoped_files_list_tool(tool: MCPTool) -> bool:
    if is_write_tool(tool):
        return False
    return conversation_scope_field(tool) is not None


def build_files_list_arguments(tool: MCPTool, conversation_id: str, limit: int) -> dict[str, Any]:
    if is_write_tool(tool) or not conversation_id:
        _deny()
    if not is_safely_scoped_files_list_tool(tool):
        _deny()
    scope = conversation_scope_field(tool)
    if scope is None:
        _deny()
    args: dict[str, Any] = {scope: conversation_id}
    field = limit_field(tool)
    if field:
        args[field] = limit
    if missing_unfillable_required(tool, set(args)):
        _deny()
    for unsafe in ACCOUNT_WIDE_QUERY_FIELDS:
        args.pop(unsafe, None)
    return args


def build_file_save_arguments(
    tool: MCPTool,
    conversation_id: str,
    *,
    save_path: str,
    file_ref: str | None = None,
    file_name: str | None = None,
    message_ref: str | None = None,
) -> dict[str, Any]:
    from app.integrations.typex_policy import is_allowed_local_save_tool

    if not is_allowed_local_save_tool(tool) or not conversation_id or not save_path:
        _deny()
    if not file_ref and not message_ref:
        _deny()
    scope = conversation_scope_field(tool)
    if scope is None:
        _deny()
    fields = set(input_field_names(tool))
    args: dict[str, Any] = {scope: conversation_id, "save_path": save_path}
    if file_ref and "file_ref" in fields:
        args["file_ref"] = file_ref
    if message_ref and not file_ref and "message_ref" in fields:
        args["message_ref"] = message_ref
    if file_name and "file_name" in fields:
        args["file_name"] = file_name
    if missing_unfillable_required(tool, set(args)):
        _deny()
    for unsafe in ACCOUNT_WIDE_QUERY_FIELDS:
        args.pop(unsafe, None)
    return args
