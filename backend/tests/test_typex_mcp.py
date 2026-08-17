import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.enums import ChatType
from app.integrations.factory import get_typex_adapter
from app.integrations.mock import MockTypeXAdapter
from app.integrations.typex import TypeXAdapter
from app.integrations.typex_errors import (
    TypeXConnectionError,
    TypeXProtocolError,
    TypeXToolUnavailableError,
)
from app.integrations.typex_mapping import map_chat, map_message
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import MCPTool, allowed_read_tools, is_write_tool

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
TEST_SEND_TOOL = MCPTool(
    name="send_message",
    description="Send a message to a chat",
    input_schema={"properties": {"chat_id": {"type": "string"}, "text": {"type": "string"}}},
)


def _rpc_result(rpc_id: int, result: object) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _tool_payload(data: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data)}]}


def _client(handler) -> TypeXMCPClient:
    return TypeXMCPClient(
        "http://127.0.0.1:52222/mcp/",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_write_tools_are_not_allowed() -> None:
    allowed = {item.name for item in allowed_read_tools([TEST_SEND_TOOL, TEST_CHAT_TOOL])}
    assert is_write_tool(TEST_SEND_TOOL) is True
    assert TEST_SEND_TOOL.name not in allowed
    assert TEST_CHAT_TOOL.name in allowed


def test_mcp_discovery_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(200, json=_rpc_result(body["id"], {"protocolVersion": "2024-11-05"}))
        if method == "notifications/initialized":
            return httpx.Response(200)
        if method == "tools/list":
            return httpx.Response(
                200,
                json=_rpc_result(
                    body["id"],
                    {
                        "tools": [
                            {"name": TEST_CHAT_TOOL.name, "description": TEST_CHAT_TOOL.description},
                            {"name": TEST_SEND_TOOL.name, "description": TEST_SEND_TOOL.description},
                        ]
                    },
                ),
            )
        raise AssertionError(method)

    client = _client(handler)
    asyncio.run(client.ensure_session())
    names = {item.name for item in client.discovered_tools}
    assert TEST_CHAT_TOOL.name in names
    assert TEST_SEND_TOOL.name in names
    assert TEST_CHAT_TOOL.name in client.allowed_tool_names
    assert TEST_SEND_TOOL.name not in client.allowed_tool_names


def test_allowed_read_tool_invocation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(200, json=_rpc_result(body["id"], {}))
        if method == "notifications/initialized":
            return httpx.Response(200)
        if method == "tools/list":
            return httpx.Response(
                200,
                json=_rpc_result(
                    body["id"],
                    {
                        "tools": [
                            {
                                "name": TEST_CHAT_TOOL.name,
                                "description": TEST_CHAT_TOOL.description,
                                "inputSchema": TEST_CHAT_TOOL.input_schema,
                            }
                        ]
                    },
                ),
            )
        if method == "tools/call":
            assert body["params"]["name"] == TEST_CHAT_TOOL.name
            return httpx.Response(
                200,
                json=_rpc_result(
                    body["id"],
                    _tool_payload([{"id": "tx-1", "name": "Affiliate John", "type": "direct"}]),
                ),
            )
        raise AssertionError(method)

    client = _client(handler)

    async def _run() -> object:
        await client.ensure_session()
        return await client.call_tool(TEST_CHAT_TOOL.name, {"limit": 20})

    payload = asyncio.run(_run())
    assert payload[0]["id"] == "tx-1"


def test_unknown_and_write_tool_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(200, json=_rpc_result(body["id"], {}))
        if method == "notifications/initialized":
            return httpx.Response(200)
        if method == "tools/list":
            return httpx.Response(
                200,
                json=_rpc_result(
                    body["id"],
                    {
                        "tools": [
                            {"name": TEST_CHAT_TOOL.name, "description": TEST_CHAT_TOOL.description},
                            {"name": TEST_SEND_TOOL.name, "description": TEST_SEND_TOOL.description},
                        ]
                    },
                ),
            )
        raise AssertionError("write tool must not be called")

    client = _client(handler)
    asyncio.run(client.ensure_session())
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool(TEST_SEND_TOOL.name, {"text": "hi"}))
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool("not_a_real_tool", {}))


def test_malformed_mcp_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = _client(handler)
    with pytest.raises(TypeXProtocolError):
        asyncio.run(client.initialize())


def test_connection_failure_and_timeout() -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = _client(fail)
    with pytest.raises(TypeXConnectionError):
        asyncio.run(client.initialize())

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    client = _client(timeout)
    with pytest.raises(TypeXConnectionError):
        asyncio.run(client.initialize())


def test_map_raw_chat_and_message_ids() -> None:
    chat = map_chat({"id": 99, "name": "Affiliate John", "type": "direct"})
    assert chat is not None
    assert chat.external_id == "99"
    assert chat.chat_type == ChatType.DIRECT
    message = map_message(
        {
            "id": 7,
            "sender_id": 5,
            "sender_name": "John",
            "text": "hello",
            "timestamp": 1750000000,
        },
        chat=chat,
        current_user_id="1",
    )
    assert message is not None
    assert message.external_id == "7"
    assert message.sender_id == "5"
    assert message.is_outgoing is False
    assert message.timestamp.tzinfo is not None


def test_outgoing_uses_account_id_not_name() -> None:
    chat = map_chat({"id": "c1", "name": "Igor"})
    assert chat is not None
    incoming = map_message(
        {
            "id": "m1",
            "sender_id": "other",
            "sender_name": "Igor",
            "text": "hi",
            "timestamp": "2026-08-17T12:00:00Z",
        },
        chat=chat,
        current_user_id="me-1",
    )
    outgoing = map_message(
        {
            "id": "m2",
            "sender_id": "me-1",
            "sender_name": "Someone",
            "text": "ok",
            "timestamp": "2026-08-17T12:01:00Z",
        },
        chat=chat,
        current_user_id="me-1",
    )
    assert incoming is not None and incoming.is_outgoing is False
    assert outgoing is not None and outgoing.is_outgoing is True


def test_unsupported_media_placeholder() -> None:
    chat = map_chat({"id": "c1", "name": "Files"})
    assert chat is not None
    voice = map_message(
        {"id": "m1", "sender_id": "u1", "type": "voice", "timestamp": 1750000000},
        chat=chat,
        current_user_id=None,
    )
    assert voice is not None
    assert voice.text == "[Voice message]"
    skipped = map_message(
        {"id": "m2", "sender_id": "u1", "type": "unknown-binary"},
        chat=chat,
        current_user_id=None,
    )
    assert skipped is None


def test_adapter_maps_discovered_tools() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(200, json=_rpc_result(body["id"], {}))
        if method == "notifications/initialized":
            return httpx.Response(200)
        if method == "tools/list":
            return httpx.Response(
                200,
                json=_rpc_result(
                    body["id"],
                    {
                        "tools": [
                            {
                                "name": TEST_CHAT_TOOL.name,
                                "description": TEST_CHAT_TOOL.description,
                                "inputSchema": TEST_CHAT_TOOL.input_schema,
                            },
                            {
                                "name": TEST_MESSAGE_TOOL.name,
                                "description": TEST_MESSAGE_TOOL.description,
                                "inputSchema": TEST_MESSAGE_TOOL.input_schema,
                            },
                            {
                                "name": TEST_ME_TOOL.name,
                                "description": TEST_ME_TOOL.description,
                                "inputSchema": TEST_ME_TOOL.input_schema,
                            },
                            {"name": TEST_SEND_TOOL.name, "description": TEST_SEND_TOOL.description},
                        ]
                    },
                ),
            )
        if method == "tools/call":
            name = body["params"]["name"]
            assert name != TEST_SEND_TOOL.name
            if name == TEST_CHAT_TOOL.name:
                data: object = [{"id": "tx-john", "name": "Affiliate John", "type": "direct"}]
            elif name == TEST_ME_TOOL.name:
                data = {"id": "igor-1", "name": "Igor"}
            else:
                data = [
                    {
                        "id": "m-1",
                        "chat_id": "tx-john",
                        "sender_id": "john-1",
                        "sender_name": "John",
                        "text": "We've started traffic today.",
                        "timestamp": "2026-08-17T10:00:00Z",
                    },
                    {
                        "id": "m-2",
                        "sender_id": "igor-1",
                        "sender_name": "Igor",
                        "text": "Thanks",
                        "timestamp": "2026-08-17T10:01:00Z",
                    },
                ]
            return httpx.Response(200, json=_rpc_result(body["id"], _tool_payload(data)))
        raise AssertionError(method)

    adapter = TypeXAdapter(_client(handler))
    chats = asyncio.run(adapter.get_chats())
    assert chats[0].external_id == "tx-john"
    messages = asyncio.run(adapter.get_messages("tx-john"))
    assert [item.external_id for item in messages] == ["m-1", "m-2"]
    assert messages[0].is_outgoing is False
    assert messages[1].is_outgoing is True


def test_factory_returns_mock() -> None:
    assert isinstance(get_typex_adapter(), MockTypeXAdapter)


def test_factory_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.typex_errors import TypeXConfigurationError

    monkeypatch.setattr(
        "app.integrations.factory.get_settings",
        lambda: SimpleNamespace(typex_mode="mystery"),
    )
    with pytest.raises(TypeXConfigurationError):
        get_typex_adapter()
