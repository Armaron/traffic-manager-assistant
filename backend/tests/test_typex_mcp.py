import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.enums import ChatType
from app.integrations.factory import get_typex_adapter
from app.integrations.mock import MockTypeXAdapter
from app.integrations.typex_errors import (
    TypeXConfigurationError,
    TypeXConnectionError,
    TypeXProtocolError,
    TypeXToolUnavailableError,
)
from app.integrations.typex_discover import possible_chat_tools, possible_message_tools, suggest_binding
from app.integrations.typex_mapping import map_chat, map_message
from app.integrations.typex_policy import diagnostic_kind, is_write_tool
from tests.typex_helpers import (
    TEST_ARCHIVE_TOOL,
    TEST_BLOCK_TOOL,
    TEST_CHAT_TOOL,
    TEST_HYBRID_TOOL,
    TEST_ME_TOOL,
    TEST_MESSAGE_TOOL,
    TEST_MUTE_TOOL,
    TEST_SEND_TOOL,
    TEST_SENDER_TOOL,
    mcp_client,
    session_handler,
    typex_adapter,
)


def test_discovery_does_not_grant_call_permission() -> None:
    tools = [
        TEST_CHAT_TOOL,
        TEST_MESSAGE_TOOL,
        TEST_SEND_TOOL,
        TEST_ARCHIVE_TOOL,
        TEST_MUTE_TOOL,
        TEST_BLOCK_TOOL,
        TEST_HYBRID_TOOL,
    ]
    client = mcp_client(session_handler(tools), allowed=set())
    asyncio.run(client.ensure_session())
    assert {item.name for item in client.discovered_tools} == {tool.name for tool in tools}
    assert client.allowed_tool_names == set()
    for name in (
        TEST_SEND_TOOL.name,
        TEST_ARCHIVE_TOOL.name,
        TEST_MUTE_TOOL.name,
        TEST_BLOCK_TOOL.name,
        TEST_HYBRID_TOOL.name,
        TEST_CHAT_TOOL.name,
    ):
        with pytest.raises(TypeXToolUnavailableError):
            asyncio.run(client.call_tool(name, {}))


def test_write_looking_tools_are_denied_unless_configured() -> None:
    calls: dict[str, list[dict]] = {}
    tools = [TEST_CHAT_TOOL, TEST_SEND_TOOL, TEST_ARCHIVE_TOOL, TEST_MUTE_TOOL, TEST_BLOCK_TOOL, TEST_HYBRID_TOOL]
    client = mcp_client(session_handler(tools, calls=calls, default_call_result=[]), allowed=set())
    asyncio.run(client.ensure_session())
    for name in (
        TEST_SEND_TOOL.name,
        TEST_ARCHIVE_TOOL.name,
        TEST_MUTE_TOOL.name,
        TEST_BLOCK_TOOL.name,
        TEST_HYBRID_TOOL.name,
    ):
        with pytest.raises(TypeXToolUnavailableError):
            asyncio.run(client.call_tool(name, {}))
    assert calls == {}


def test_keyword_hybrid_tool_is_not_authorized_by_discovery() -> None:
    client = mcp_client(session_handler([TEST_HYBRID_TOOL, TEST_CHAT_TOOL]), allowed=set())
    asyncio.run(client.ensure_session())
    assert TEST_HYBRID_TOOL.name in {item.name for item in client.discovered_tools}
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool(TEST_HYBRID_TOOL.name, {"chat_id": "c1"}))


def test_configured_exact_read_tool_can_be_called() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TEST_CHAT_TOOL, TEST_SEND_TOOL],
        calls=calls,
        call_results={TEST_CHAT_TOOL.name: [{"id": "tx-1", "name": "Affiliate John", "type": "direct"}]},
    )
    client = mcp_client(handler, allowed={TEST_CHAT_TOOL.name})
    payload = asyncio.run(client.call_tool(TEST_CHAT_TOOL.name, {"limit": 20}))
    assert payload[0]["id"] == "tx-1"
    assert TEST_SEND_TOOL.name not in calls
    assert calls[TEST_CHAT_TOOL.name] == [{"limit": 20}]


def test_configured_tool_missing_from_discovery_fails() -> None:
    client = mcp_client(session_handler([TEST_CHAT_TOOL]), allowed={"missing_tool", TEST_CHAT_TOOL.name})
    asyncio.run(client.ensure_session())
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool("missing_tool", {}))


def test_unknown_tool_fails() -> None:
    client = mcp_client(session_handler([TEST_CHAT_TOOL]), allowed={TEST_CHAT_TOOL.name})
    asyncio.run(client.ensure_session())
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool("not_a_real_tool", {}))


def test_archive_can_be_called_only_when_explicitly_configured() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TEST_ARCHIVE_TOOL, TEST_CHAT_TOOL],
        calls=calls,
        call_results={TEST_ARCHIVE_TOOL.name: []},
    )
    denied = mcp_client(handler, allowed={TEST_CHAT_TOOL.name})
    asyncio.run(denied.ensure_session())
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(denied.call_tool(TEST_ARCHIVE_TOOL.name, {}))
    allowed = mcp_client(handler, allowed={TEST_ARCHIVE_TOOL.name})
    asyncio.run(allowed.call_tool(TEST_ARCHIVE_TOOL.name, {"conversation_id": "c1"}))
    assert TEST_ARCHIVE_TOOL.name in allowed.allowed_tool_names
    assert calls[TEST_ARCHIVE_TOOL.name] == [{"conversation_id": "c1"}]


def test_diagnostic_kind_does_not_authorize() -> None:
    assert is_write_tool(TEST_SEND_TOOL) is True
    assert diagnostic_kind(TEST_ARCHIVE_TOOL) == "write"
    assert diagnostic_kind(TEST_CHAT_TOOL) == "read"
    assert diagnostic_kind(TEST_HYBRID_TOOL) == "write"


def test_discover_suggestions_are_not_authorization() -> None:
    chats = possible_chat_tools([TEST_CHAT_TOOL, TEST_ARCHIVE_TOOL, TEST_MESSAGE_TOOL])
    messages = possible_message_tools([TEST_MESSAGE_TOOL, TEST_HYBRID_TOOL])
    assert [tool.name for tool in chats] == [TEST_CHAT_TOOL.name]
    assert [tool.name for tool in messages] == [TEST_MESSAGE_TOOL.name]
    assert suggest_binding(chats) == TEST_CHAT_TOOL.name
    assert suggest_binding(chats + chats) == ""
    assert suggest_binding([]) == ""


def test_malformed_mcp_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = mcp_client(handler)
    with pytest.raises(TypeXProtocolError):
        asyncio.run(client.initialize())


def test_connection_failure_and_timeout() -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = mcp_client(fail)
    with pytest.raises(TypeXConnectionError):
        asyncio.run(client.initialize())

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    client = mcp_client(timeout)
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


def test_explicit_outgoing_true() -> None:
    chat = map_chat({"id": "c1", "name": "John"})
    assert chat is not None
    message = map_message(
        {
            "id": "m1",
            "sender_id": "other",
            "text": "hi",
            "timestamp": "2026-08-17T12:00:00Z",
            "is_outgoing": True,
        },
        chat=chat,
        current_user_id=None,
    )
    assert message is not None
    assert message.is_outgoing is True


def test_explicit_outgoing_false() -> None:
    chat = map_chat({"id": "c1", "name": "John"})
    assert chat is not None
    message = map_message(
        {
            "id": "m1",
            "sender_id": "me",
            "text": "hi",
            "timestamp": "2026-08-17T12:00:00Z",
            "is_outgoing": False,
        },
        chat=chat,
        current_user_id="me",
    )
    assert message is not None
    assert message.is_outgoing is False


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


def test_unknown_direction_is_not_incoming() -> None:
    chat = map_chat({"id": "c1", "name": "John"})
    assert chat is not None
    skipped = map_message(
        {
            "id": "m1",
            "sender_id": "u1",
            "text": "hello",
            "timestamp": "2026-08-17T12:00:00Z",
        },
        chat=chat,
        current_user_id=None,
    )
    assert skipped is None


def test_unsupported_media_placeholder() -> None:
    chat = map_chat({"id": "c1", "name": "Files"})
    assert chat is not None
    voice = map_message(
        {
            "id": "m1",
            "sender_id": "u1",
            "type": "voice",
            "timestamp": 1750000000,
            "is_outgoing": False,
        },
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


def test_adapter_uses_exact_configured_tools_not_heuristics() -> None:
    configured_chats = "list_typex_chats"
    configured_messages = "list_typex_messages"
    heuristic_chat = TEST_CHAT_TOOL
    calls: dict[str, list[dict]] = {}
    chats_tool = TEST_CHAT_TOOL.__class__(
        name=configured_chats,
        description="List chats",
        input_schema={"properties": {"limit": {"type": "integer"}}},
    )
    messages_tool = TEST_MESSAGE_TOOL.__class__(
        name=configured_messages,
        description="List messages",
        input_schema={
            "properties": {
                "conversation_id": {"type": "string"},
                "limit": {"type": "integer"},
            }
        },
    )
    handler = session_handler(
        [heuristic_chat, chats_tool, messages_tool, TEST_ME_TOOL, TEST_SEND_TOOL],
        calls=calls,
        call_results={
            configured_chats: [{"id": "tx-john", "name": "Affiliate John", "type": "direct"}],
            configured_messages: [
                {
                    "id": "m-1",
                    "chat_id": "tx-john",
                    "sender_id": "john-1",
                    "sender_name": "John",
                    "text": "We've started traffic today.",
                    "timestamp": "2026-08-17T10:00:00Z",
                    "is_outgoing": False,
                },
                {
                    "id": "m-2",
                    "sender_id": "igor-1",
                    "sender_name": "Igor",
                    "text": "Thanks",
                    "timestamp": "2026-08-17T10:01:00Z",
                    "is_outgoing": True,
                },
            ],
            TEST_ME_TOOL.name: {"id": "igor-1", "name": "Igor"},
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=configured_chats,
        messages_tool=configured_messages,
        current_user_tool=TEST_ME_TOOL.name,
    )
    chats = asyncio.run(adapter.get_chats())
    messages = asyncio.run(adapter.get_messages("tx-john"))
    assert chats[0].external_id == "tx-john"
    assert [item.external_id for item in messages] == ["m-1", "m-2"]
    assert messages[0].is_outgoing is False
    assert messages[1].is_outgoing is True
    assert heuristic_chat.name not in calls
    assert TEST_SEND_TOOL.name not in calls
    assert configured_chats in calls
    assert configured_messages in calls
    assert calls[configured_messages][0]["conversation_id"] == "tx-john"
    assert calls[configured_messages][0]["limit"] == 50


def test_message_tool_without_chat_id_schema_fails() -> None:
    calls: dict[str, list[dict]] = {}
    unsafe = TEST_MESSAGE_TOOL.__class__(
        name="search_all_messages",
        description="Search messages across the account",
        input_schema={"properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
    )
    handler = session_handler([TEST_CHAT_TOOL, unsafe], calls=calls, default_call_result=[])
    adapter = typex_adapter(
        handler,
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=unsafe.name,
        current_user_tool=None,
    )
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(adapter.get_messages("tx-john"))
    assert unsafe.name not in calls


def test_limit_passed_when_supported_and_local_slice_when_not() -> None:
    unlimited = TEST_MESSAGE_TOOL.__class__(
        name="chat_history",
        description="Chat history",
        input_schema={"properties": {"chat_id": {"type": "string"}}},
    )
    calls: dict[str, list[dict]] = {}
    rows = [
        {
            "id": f"m-{index}",
            "sender_id": "john-1",
            "text": f"msg {index}",
            "timestamp": f"2026-08-17T10:00:{index:02d}Z",
            "is_outgoing": False,
        }
        for index in range(5)
    ]
    handler = session_handler(
        [TEST_CHAT_TOOL, unlimited],
        calls=calls,
        call_results={unlimited.name: rows},
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=unlimited.name,
        current_user_tool=None,
        message_limit=2,
    )
    messages = asyncio.run(adapter.get_messages("tx-john"))
    assert "limit" not in calls[unlimited.name][0]
    assert calls[unlimited.name][0]["chat_id"] == "tx-john"
    assert [item.external_id for item in messages] == ["m-3", "m-4"]


def test_optional_sender_tool_absence_is_safe() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler([TEST_CHAT_TOOL, TEST_MESSAGE_TOOL, TEST_SENDER_TOOL], calls=calls)
    adapter = typex_adapter(
        handler,
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=TEST_MESSAGE_TOOL.name,
        current_user_tool=None,
        sender_tool=None,
    )
    assert asyncio.run(adapter.get_sender("john-1")) is None
    assert TEST_SENDER_TOOL.name not in calls


def test_blank_required_tools_block_sync_readiness() -> None:
    adapter = typex_adapter(
        session_handler([TEST_CHAT_TOOL, TEST_MESSAGE_TOOL]),
        chats_tool=None,
        messages_tool=None,
        current_user_tool=None,
    )
    with pytest.raises(TypeXConfigurationError):
        asyncio.run(adapter.ensure_ready_for_sync())


def test_unknown_direction_increments_skipped() -> None:
    handler = session_handler(
        [TEST_CHAT_TOOL, TEST_MESSAGE_TOOL],
        call_results={
            TEST_MESSAGE_TOOL.name: [
                {
                    "id": "ok",
                    "sender_id": "john-1",
                    "text": "hello",
                    "timestamp": "2026-08-17T10:00:00Z",
                    "is_outgoing": False,
                },
                {
                    "id": "skip",
                    "sender_id": "maybe-me",
                    "text": "???",
                    "timestamp": "2026-08-17T10:01:00Z",
                },
            ]
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=TEST_MESSAGE_TOOL.name,
        current_user_tool=None,
    )
    messages = asyncio.run(adapter.get_messages("tx-john"))
    assert [item.external_id for item in messages] == ["ok"]
    assert adapter.last_messages_seen == 2
    assert adapter.last_messages_skipped == 1


def test_factory_returns_mock() -> None:
    assert isinstance(get_typex_adapter(), MockTypeXAdapter)


def test_factory_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.integrations.factory.get_settings",
        lambda: SimpleNamespace(typex_mode="mystery"),
    )
    with pytest.raises(TypeXConfigurationError):
        get_typex_adapter()
