from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from app.integrations.typex import TypeXAdapter
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import MCPTool

TEST_CHAT_TOOL = MCPTool(
    name="search_conversations",
    description="Search chats and groups",
    input_schema={"properties": {"limit": {"type": "integer"}}},
)
TEST_MESSAGE_TOOL = MCPTool(
    name="search_messages",
    description="Search messages in a conversation",
    input_schema={
        "properties": {
            "chat_id": {"type": "string"},
            "limit": {"type": "integer"},
        }
    },
)
TEST_ME_TOOL = MCPTool(
    name="get_current_user",
    description="Return the signed-in TypeX account",
    input_schema={"properties": {}},
)
TEST_SENDER_TOOL = MCPTool(
    name="get_user",
    description="Return a TypeX user profile",
    input_schema={"properties": {"user_id": {"type": "string"}}},
)
TEST_SEND_TOOL = MCPTool(
    name="send_message",
    description="Send a message to a chat",
    input_schema={"properties": {"chat_id": {"type": "string"}, "text": {"type": "string"}}},
)
TEST_ARCHIVE_TOOL = MCPTool(
    name="archive_conversation",
    description="Archive a conversation",
    input_schema={"properties": {"conversation_id": {"type": "string"}}},
)
TEST_MUTE_TOOL = MCPTool(
    name="mute_chat",
    description="Mute a chat",
    input_schema={"properties": {"chat_id": {"type": "string"}}},
)
TEST_BLOCK_TOOL = MCPTool(
    name="block_user",
    description="Block a user",
    input_schema={"properties": {"user_id": {"type": "string"}}},
)
TEST_HYBRID_TOOL = MCPTool(
    name="get_and_delete_messages",
    description="Get messages then delete them",
    input_schema={"properties": {"chat_id": {"type": "string"}}},
)


def rpc_result(rpc_id: int, result: object) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def tool_payload(data: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data)}]}


def tool_json(tool: MCPTool) -> dict:
    payload: dict = {"name": tool.name, "description": tool.description}
    if tool.input_schema is not None:
        payload["inputSchema"] = tool.input_schema
    return payload


def mcp_client(handler: Callable[[httpx.Request], httpx.Response], allowed: set[str] | None = None) -> TypeXMCPClient:
    return TypeXMCPClient(
        "http://127.0.0.1:52222/mcp/",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        allowed_tool_names=allowed or set(),
    )


def session_handler(
    tools: list[MCPTool],
    calls: dict[str, list[dict]] | None = None,
    call_results: dict[str, object] | None = None,
    default_call_result: object | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    recorded = calls if calls is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(200, json=rpc_result(body["id"], {"protocolVersion": "2024-11-05"}))
        if method == "notifications/initialized":
            return httpx.Response(200)
        if method == "tools/list":
            return httpx.Response(
                200,
                json=rpc_result(body["id"], {"tools": [tool_json(tool) for tool in tools]}),
            )
        if method == "tools/call":
            name = body["params"]["name"]
            recorded.setdefault(name, []).append(body["params"].get("arguments") or {})
            if call_results is not None and name in call_results:
                data = call_results[name]
            elif default_call_result is not None:
                data = default_call_result
            else:
                raise AssertionError(f"unexpected tools/call {name}")
            return httpx.Response(200, json=rpc_result(body["id"], tool_payload(data)))
        raise AssertionError(method)

    return handler


def typex_adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    chats_tool: str | None = TEST_CHAT_TOOL.name,
    messages_tool: str | None = TEST_MESSAGE_TOOL.name,
    current_user_tool: str | None = TEST_ME_TOOL.name,
    sender_tool: str | None = None,
    chat_limit: int = 20,
    message_limit: int = 50,
) -> TypeXAdapter:
    allowed = {name for name in (chats_tool, messages_tool, current_user_tool, sender_tool) if name}
    return TypeXAdapter(
        mcp_client(handler, allowed),
        chats_tool=chats_tool,
        messages_tool=messages_tool,
        current_user_tool=current_user_tool,
        sender_tool=sender_tool,
        chat_limit=chat_limit,
        message_limit=message_limit,
    )
