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
    TypeXToolCallError,
    TypeXToolUnavailableError,
    public_typex_message,
)
from app.integrations.typex_discover import possible_chat_tools, possible_message_tools, suggest_binding
from app.integrations.typex_mapping import map_chat, map_message, map_sender
from app.integrations.typex_policy import diagnostic_kind, is_write_tool
from tests.typex_helpers import (
    TEST_ARCHIVE_TOOL,
    TEST_BLOCK_TOOL,
    TEST_CHAT_TOOL,
    TEST_CREATE_TOOL,
    TEST_EDIT_TOOL,
    TEST_HYBRID_TOOL,
    TEST_ME_TOOL,
    TEST_MESSAGE_TOOL,
    TEST_MUTE_TOOL,
    TEST_REPLY_TOOL,
    TEST_SEND_TOOL,
    TEST_SENDER_TOOL,
    TEST_UPLOAD_TOOL,
    TYPEX_ACCOUNT_WIDE_SEARCH,
    TYPEX_GET_ME,
    TYPEX_LIST_FOLDER_FEEDS,
    TYPEX_SEARCH_CHAT_RECORDS,
    TYPEX_SEARCH_CONTACT,
    TYPEX_SEND_MESSAGE,
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


def test_configured_write_tools_are_denied() -> None:
    calls: dict[str, list[dict]] = {}
    tools = [
        TEST_CHAT_TOOL,
        TEST_SEND_TOOL,
        TEST_ARCHIVE_TOOL,
        TEST_MUTE_TOOL,
        TEST_BLOCK_TOOL,
        TEST_HYBRID_TOOL,
        TEST_EDIT_TOOL,
        TEST_REPLY_TOOL,
        TEST_CREATE_TOOL,
        TEST_UPLOAD_TOOL,
        TYPEX_SEND_MESSAGE,
    ]
    handler = session_handler(tools, calls=calls, default_call_result=[])
    for tool in tools[1:]:
        client = mcp_client(handler, allowed={tool.name})
        with pytest.raises(TypeXToolUnavailableError):
            asyncio.run(client.call_tool(tool.name, {}))
        assert tool.name not in calls


def test_configured_read_get_me_is_not_blocked_by_description() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_GET_ME],
        calls=calls,
        call_results={TYPEX_GET_ME.name: {"id": "acct-1", "name": "Operator"}},
    )
    client = mcp_client(handler, allowed={TYPEX_GET_ME.name})
    payload = asyncio.run(client.call_tool(TYPEX_GET_ME.name, {}))
    assert payload["id"] == "acct-1"
    assert TYPEX_GET_ME.name in calls
    assert is_write_tool(TYPEX_GET_ME) is False
    assert diagnostic_kind(TYPEX_GET_ME) == "write"


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


def test_tools_call_is_error_is_not_success() -> None:
    sensitive = "sensitive internal TypeX error"
    handler = session_handler(
        [TEST_CHAT_TOOL],
        call_results={
            TEST_CHAT_TOOL.name: {
                "isError": True,
                "content": [{"type": "text", "text": sensitive}],
            }
        },
    )
    client = mcp_client(handler, allowed={TEST_CHAT_TOOL.name})
    with pytest.raises(TypeXToolCallError) as exc_info:
        asyncio.run(client.call_tool(TEST_CHAT_TOOL.name, {"limit": 1}))
    public = public_typex_message(exc_info.value)
    assert sensitive not in str(exc_info.value)
    assert sensitive not in public
    assert public == "TypeX MCP unavailable"
    assert isinstance(exc_info.value, TypeXProtocolError)


def test_typex_feed_without_stable_id_is_not_mapped() -> None:
    chat = map_chat(
        {
            "name": "Affiliate John",
            "last_message_send_at": "2026-08-17T10:00:00Z",
            "chat_type": 1,
            "chat_type_label": "direct",
        }
    )
    assert chat is None
    chat = map_chat(
        {
            "opaque_ref": "feed-opaque-1",
            "name": "Affiliate John",
            "type": "direct",
        }
    )
    assert chat is not None
    assert chat.external_id == "feed-opaque-1"
    assert chat.name == "Affiliate John"
    assert chat.chat_type == ChatType.DIRECT


def test_live_style_chat_record_without_direction_is_skipped() -> None:
    chat = map_chat({"opaque_ref": "ref-1", "name": "Affiliate John", "chat_type_label": "single chat"})
    assert chat is not None
    skipped = map_message(
        {
            "message_ref": "msg-1",
            "message_type": "text",
            "send_name": "John",
            "send_at": "2026-08-17T10:00:00Z",
            "content": "hello",
        },
        chat=chat,
        current_user_id="acct-1",
    )
    assert skipped is None
    kept = map_message(
        {
            "message_ref": "msg-2",
            "message_type": "text",
            "send_name": "John",
            "send_at": "2026-08-17T10:00:00Z",
            "content": "hello",
            "is_outgoing": False,
        },
        chat=chat,
        current_user_id="acct-1",
    )
    assert kept is not None
    assert kept.external_id == "msg-2"
    assert kept.sender_name == "John"
    assert kept.is_outgoing is False


def test_typex_chat_record_schema_mapping() -> None:
    chat = map_chat({"opaque_ref": "feed-opaque-1", "name": "Affiliate John", "type": "direct"})
    assert chat is not None
    message = map_message(
        {
            "message_ref": "msg-1",
            "chat_ref": "feed-opaque-1",
            "sender_id": "u-1",
            "sender_name": "John",
            "content": "hello",
            "send_time": "2026-08-17T10:00:00Z",
            "is_outgoing": False,
        },
        chat=chat,
        current_user_id="me-1",
    )
    assert message is not None
    assert message.external_id == "msg-1"
    assert message.chat_id == "feed-opaque-1"
    assert message.chat_name == "Affiliate John"
    assert message.sender_id == "u-1"
    assert message.text == "hello"
    assert message.is_outgoing is False


def test_get_me_mapping() -> None:
    sender = map_sender({"id": "acct-1", "name": "Operator"})
    assert sender is not None
    assert sender.external_id == "acct-1"
    assert sender.name == "Operator"


def test_get_me_nested_prefers_stable_id() -> None:
    from app.integrations.typex_mapping import map_current_user

    sender = map_current_user(
        {
            "ok": True,
            "me": {
                "id": "acct-1",
                "uid": "uid-9",
                "typex_id": "tx-9",
                "name": "Operator",
            },
            "summary": "redacted",
        }
    )
    assert sender is not None
    assert sender.external_id == "acct-1"
    assert sender.name == "Operator"


def test_real_typex_bindings_construct_scoped_arguments() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_LIST_FOLDER_FEEDS, TYPEX_SEARCH_CHAT_RECORDS, TYPEX_GET_ME],
        calls=calls,
        call_results={
            TYPEX_LIST_FOLDER_FEEDS.name: [
                {"opaque_ref": "feed-opaque-1", "name": "Affiliate John", "type": "direct"}
            ],
            TYPEX_SEARCH_CHAT_RECORDS.name: [
                {
                    "message_ref": "msg-1",
                    "sender_id": "u-1",
                    "sender_name": "John",
                    "content": "hello",
                    "send_time": "2026-08-17T10:00:00Z",
                    "is_outgoing": False,
                }
            ],
            TYPEX_GET_ME.name: {"id": "acct-1", "name": "Operator"},
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=TYPEX_GET_ME.name,
    )
    chats = asyncio.run(adapter.get_chats())
    messages = asyncio.run(adapter.get_messages("feed-opaque-1"))
    assert chats[0].external_id == "feed-opaque-1"
    assert chats[0].name == "Affiliate John"
    assert messages[0].chat_name == "Affiliate John"
    assert calls[TYPEX_LIST_FOLDER_FEEDS.name][0] == {"all_chats": True, "limit": 20}
    assert calls[TYPEX_SEARCH_CHAT_RECORDS.name][0] == {"opaque_ref": "feed-opaque-1", "limit": 50}
    assert "query" not in calls[TYPEX_SEARCH_CHAT_RECORDS.name][0]
    assert "contact_name" not in calls[TYPEX_SEARCH_CHAT_RECORDS.name][0]
    assert TYPEX_SEND_MESSAGE.name not in calls


def test_unknown_required_argument_fails_closed() -> None:
    calls: dict[str, list[dict]] = {}
    unsafe = TEST_MESSAGE_TOOL.__class__(
        name="search_messages",
        description="Search messages in a conversation",
        input_schema={
            "properties": {
                "chat_id": {"type": "string"},
                "secret_token": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["chat_id", "secret_token"],
        },
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


def test_account_wide_search_rejected_as_messages_role() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_LIST_FOLDER_FEEDS, TYPEX_ACCOUNT_WIDE_SEARCH, TYPEX_SEARCH_CONTACT],
        calls=calls,
        default_call_result=[],
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_ACCOUNT_WIDE_SEARCH.name,
        current_user_tool=None,
    )
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(adapter.ensure_ready_for_sync())
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(adapter.get_messages("feed-opaque-1"))
    assert TYPEX_ACCOUNT_WIDE_SEARCH.name not in calls


def test_fuzzy_search_contact_rejected_as_sender_tool() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_LIST_FOLDER_FEEDS, TYPEX_SEARCH_CHAT_RECORDS, TYPEX_SEARCH_CONTACT],
        calls=calls,
        default_call_result=[],
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=None,
        sender_tool=TYPEX_SEARCH_CONTACT.name,
    )
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(adapter.ensure_ready_for_sync())
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(adapter.get_sender("u-1"))
    assert TYPEX_SEARCH_CONTACT.name not in calls


def test_configured_send_message_as_chats_tool_is_denied() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_SEND_MESSAGE, TYPEX_SEARCH_CHAT_RECORDS],
        calls=calls,
        default_call_result=[],
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_SEND_MESSAGE.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=None,
    )
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(adapter.ensure_ready_for_sync())
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(adapter.get_chats())
    assert TYPEX_SEND_MESSAGE.name not in calls


def test_adapter_skips_unknown_direction_and_does_not_send() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_LIST_FOLDER_FEEDS, TYPEX_SEARCH_CHAT_RECORDS, TYPEX_SEND_MESSAGE],
        calls=calls,
        call_results={
            TYPEX_LIST_FOLDER_FEEDS.name: [{"opaque_ref": "feed-1", "name": "Chat"}],
            TYPEX_SEARCH_CHAT_RECORDS.name: [
                {
                    "message_ref": "ok",
                    "sender_id": "u-1",
                    "content": "hello",
                    "send_time": "2026-08-17T10:00:00Z",
                    "is_outgoing": False,
                },
                {
                    "message_ref": "skip",
                    "sender_id": "maybe-me",
                    "content": "???",
                    "send_time": "2026-08-17T10:01:00Z",
                },
            ],
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=None,
    )
    messages = asyncio.run(adapter.get_messages("feed-1"))
    assert [item.external_id for item in messages] == ["ok"]
    assert adapter.last_messages_seen == 2
    assert adapter.last_messages_skipped == 1
    assert TYPEX_SEND_MESSAGE.name not in calls
