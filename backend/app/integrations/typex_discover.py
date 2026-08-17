import asyncio
import logging
import sys

from app.integrations.typex_bindings import is_safely_scoped_messages_tool, sender_lookup_is_exact
from app.integrations.typex_errors import TypeXError
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import (
    MCPTool,
    diagnostic_kind,
    input_field_names,
    is_write_tool,
    required_field_names,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHAT_NAME_HINTS = ("conversation", "chat", "dialog", "group", "feed", "folder")
MESSAGE_NAME_HINTS = ("message", "history", "record")
CURRENT_USER_NAME_HINTS = ("current_user", "currentuser", "get_me", "whoami", "self")
SENDER_NAME_HINTS = ("user", "contact", "profile", "sender")


def _name_blob(tool: MCPTool) -> str:
    return tool.name.lower().replace("-", "_")


def _matches_any(blob: str, hints: tuple[str, ...]) -> bool:
    return any(hint in blob for hint in hints)


def _printable(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def possible_chat_tools(tools: list[MCPTool]) -> list[MCPTool]:
    found: list[MCPTool] = []
    for tool in tools:
        if is_write_tool(tool):
            continue
        blob = _name_blob(tool)
        if not _matches_any(blob, CHAT_NAME_HINTS):
            continue
        if _matches_any(blob, MESSAGE_NAME_HINTS):
            continue
        found.append(tool)
    return found


def possible_message_tools(tools: list[MCPTool]) -> list[MCPTool]:
    found: list[MCPTool] = []
    for tool in tools:
        if is_write_tool(tool):
            continue
        blob = _name_blob(tool)
        if not _matches_any(blob, MESSAGE_NAME_HINTS):
            continue
        if not is_safely_scoped_messages_tool(tool):
            continue
        found.append(tool)
    return found


def possible_current_user_tools(tools: list[MCPTool]) -> list[MCPTool]:
    found: list[MCPTool] = []
    for tool in tools:
        if is_write_tool(tool):
            continue
        blob = _name_blob(tool)
        if blob.endswith("get_me") or blob in {"me", "get_me"} or _matches_any(blob, CURRENT_USER_NAME_HINTS):
            found.append(tool)
            continue
        if "current" in blob and "user" in blob:
            found.append(tool)
    return found


def possible_sender_tools(tools: list[MCPTool]) -> list[MCPTool]:
    current = {tool.name for tool in possible_current_user_tools(tools)}
    found: list[MCPTool] = []
    for tool in tools:
        if tool.name in current:
            continue
        if is_write_tool(tool):
            continue
        if not sender_lookup_is_exact(tool):
            continue
        blob = _name_blob(tool)
        if _matches_any(blob, SENDER_NAME_HINTS) and not _matches_any(blob, CHAT_NAME_HINTS + MESSAGE_NAME_HINTS):
            found.append(tool)
    return found


def suggest_binding(candidates: list[MCPTool]) -> str:
    if len(candidates) != 1:
        return ""
    return candidates[0].name


def _print_candidates(title: str, tools: list[MCPTool]) -> None:
    print(f"{title}:")
    if not tools:
        print("  (none with enough confidence)")
        return
    for tool in tools:
        fields = input_field_names(tool)
        required = required_field_names(tool)
        print(_printable(f"  * {tool.name}  required={required}  properties={fields}"))


async def main() -> None:
    client = TypeXMCPClient.from_settings()
    try:
        await client.ensure_session()
    except TypeXError as exc:
        logger.error("typex_discover failed error_type=%s", type(exc).__name__)
        print("Live MCP discovery not performed.", file=sys.stderr)
        raise SystemExit(1) from None

    print(f"endpoint={client.base_url}")
    print(f"tools={len(client.discovered_tools)}")
    print("classification is informational only; it does not grant runtime permission.")
    print()
    for tool in client.discovered_tools:
        kind = diagnostic_kind(tool)
        auth_write = is_write_tool(tool)
        fields = input_field_names(tool)
        required = required_field_names(tool)
        print(
            _printable(
                f"{tool.name}\tkind={kind}\tauth_write={auth_write}\t"
                f"required={required}\tproperties={fields}"
            )
        )
        if tool.description:
            print(_printable(f"  {tool.description[:180]}"))

    chats = possible_chat_tools(client.discovered_tools)
    messages = possible_message_tools(client.discovered_tools)
    current_user = possible_current_user_tools(client.discovered_tools)
    senders = possible_sender_tools(client.discovered_tools)

    print()
    _print_candidates("Possible chat tools", chats)
    _print_candidates("Possible message tools", messages)
    _print_candidates("Possible current-user tools", current_user)
    _print_candidates("Possible sender tools", senders)

    print()
    print("Suggested configuration:")
    print("# Fill these after reviewing discovery. Do not guess tool names.")
    print("# Suggestions are not authorization and are not written to .env.")
    print(f"TYPEX_CHATS_TOOL={suggest_binding(chats)}")
    print(f"TYPEX_MESSAGES_TOOL={suggest_binding(messages)}")
    print(f"TYPEX_CURRENT_USER_TOOL={suggest_binding(current_user)}")
    print(f"TYPEX_SENDER_TOOL={suggest_binding(senders)}")


if __name__ == "__main__":
    asyncio.run(main())
