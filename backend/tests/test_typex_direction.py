from app.enums import ChatType, MessageDirection
from app.integrations.typex_direction import (
    TypeXDirectionContext,
    TypeXIdentity,
    resolve_typex_direction,
)
from app.integrations.typex_errors import TypeXToolUnavailableError
from app.integrations.typex_mapping import map_chat, map_message
from tests.typex_helpers import (
    TEST_CHAT_TOOL,
    TEST_SEND_TOOL,
    TYPEX_SEARCH_CONTACT,
    mcp_client,
    session_handler,
)
import asyncio
import pytest


from app.enums import ChatType, MessageDirection
from app.integrations.typex_direction import (
    TypeXDirectionContext,
    TypeXIdentity,
    resolve_typex_direction,
)
from app.integrations.typex_errors import TypeXToolUnavailableError
from app.integrations.typex_mapping import map_chat, map_message
from tests.typex_helpers import (
    TEST_CHAT_TOOL,
    TEST_SEND_TOOL,
    TYPEX_SEARCH_CONTACT,
    mcp_client,
    session_handler,
)
import asyncio
import pytest


def _ctx(
    *,
    chat_type: ChatType = ChatType.DIRECT,
    current: TypeXIdentity | None = None,
    counterpart: TypeXIdentity | None = None,
    current_user_exact_name: str | None = None,
    current_user_exact_names: tuple[str, ...] = (),
) -> TypeXDirectionContext:
    return TypeXDirectionContext(
        chat_type=chat_type,
        current_user=current or TypeXIdentity(),
        counterpart=counterpart,
        current_user_exact_name=current_user_exact_name,
        current_user_exact_names=current_user_exact_names,
    )


def test_explicit_outgoing_true() -> None:
    assert resolve_typex_direction({"is_outgoing": True}, _ctx()).direction is MessageDirection.OUTGOING


def test_explicit_outgoing_false() -> None:
    assert resolve_typex_direction({"is_outgoing": False}, _ctx()).direction is MessageDirection.INCOMING


def test_stable_typex_id_matches_current_user_outgoing() -> None:
    context = _ctx(current=TypeXIdentity(typex_id="me-tx"))
    assert resolve_typex_direction({"typex_id": "me-tx"}, context).direction is MessageDirection.OUTGOING


def test_stable_typex_id_matches_counterpart_incoming() -> None:
    context = _ctx(
        current=TypeXIdentity(typex_id="me-tx"),
        counterpart=TypeXIdentity(typex_id="john-tx"),
    )
    assert resolve_typex_direction({"typex_id": "john-tx"}, context).direction is MessageDirection.INCOMING


def test_different_namespace_does_not_match() -> None:
    context = _ctx(current=TypeXIdentity(account_id="acct-1"))
    assert resolve_typex_direction({"uid": "acct-1"}, context).direction is MessageDirection.UNKNOWN


def test_unknown_stable_sender_unresolved() -> None:
    assert resolve_typex_direction({"sender_id": "unknown"}, _ctx()).direction is MessageDirection.UNKNOWN


def test_other_typex_id_in_same_namespace_is_incoming() -> None:
    context = _ctx(current=TypeXIdentity(typex_id="me-tx"))
    assert resolve_typex_direction({"typex_id": "someone-else"}, context).direction is MessageDirection.INCOMING


def test_no_sender_identity_unresolved() -> None:
    context = _ctx(current=TypeXIdentity(account_id="acct-1", typex_id="me-tx"))
    assert resolve_typex_direction({"send_name": "John", "content": "hello"}, context).direction is MessageDirection.UNKNOWN


def test_exact_self_display_name_is_outgoing() -> None:
    context = _ctx(current_user_exact_name="Igor - Paid Traffic Manager Am")
    result = resolve_typex_direction(
        {"send_name": "Igor - Paid Traffic Manager Am", "content": "hello"},
        context,
    )
    assert result.direction is MessageDirection.OUTGOING
    assert result.source.value == "profile_name"


def test_other_display_name_stays_unknown_even_when_self_name_is_known() -> None:
    context = _ctx(current_user_exact_name="Igor - Paid Traffic Manager Am")
    result = resolve_typex_direction({"send_name": "John", "content": "hello"}, context)
    assert result.direction is MessageDirection.UNKNOWN
    assert result.source.value == "unknown"


def test_configured_self_name_matches_when_get_me_name_differs() -> None:
    context = _ctx(
        current_user_exact_name="Operator",
        current_user_exact_names=("Igor - Paid Traffic Manager Am",),
    )
    result = resolve_typex_direction(
        {"send_name": "Igor - Paid Traffic Manager Am", "content": "hello"},
        context,
    )
    assert result.direction is MessageDirection.OUTGOING


def test_whitespace_self_display_name_is_outgoing() -> None:
    context = _ctx(current_user_exact_name="  Igor - Paid Traffic Manager Am  ")
    result = resolve_typex_direction(
        {"send_name": "Igor - Paid Traffic Manager Am", "content": "hello"},
        context,
    )
    assert result.direction is MessageDirection.OUTGOING


def test_group_without_sender_id_unresolved() -> None:
    context = _ctx(
        chat_type=ChatType.GROUP,
        current=TypeXIdentity(typex_id="me-tx", account_id="acct-1"),
    )
    assert resolve_typex_direction({"send_name": "John", "content": "hello"}, context).direction is MessageDirection.UNKNOWN


def test_live_style_record_kept_as_unknown_even_with_current_user_context() -> None:
    chat = map_chat({"opaque_ref": "ref-1", "name": "Affiliate John", "chat_type_label": "single chat"})
    assert chat is not None
    mapped = map_message(
        {
            "message_ref": "msg-1",
            "send_name": "John",
            "send_at": "2026-08-17T10:00:00Z",
            "content": "hello",
        },
        chat=chat,
        current_user_id="acct-1",
        direction_context=_ctx(
            current=TypeXIdentity(account_id="acct-1", uid="uid-1", typex_id="me-tx"),
            counterpart=TypeXIdentity(typex_id="john-tx"),
            current_user_exact_name="Operator",
        ),
    )
    assert mapped is not None
    assert mapped.direction is MessageDirection.UNKNOWN
    assert mapped.sender_id is None
    assert mapped.sender_name == "John"
    assert mapped.is_outgoing is False


def test_live_style_self_send_name_is_outgoing() -> None:
    chat = map_chat({"opaque_ref": "ref-1", "name": "Affiliate John", "chat_type_label": "single chat"})
    assert chat is not None
    mapped = map_message(
        {
            "message_ref": "msg-self",
            "send_name": "Igor - Paid Traffic Manager Am",
            "send_at": "2026-08-17T10:00:00Z",
            "content": "hello",
        },
        chat=chat,
        current_user_id="acct-1",
        direction_context=_ctx(
            current=TypeXIdentity(account_id="acct-1"),
            current_user_exact_name="Igor - Paid Traffic Manager Am",
        ),
    )
    assert mapped is not None
    assert mapped.direction is MessageDirection.OUTGOING
    assert mapped.direction_source.value == "profile_name"
    assert mapped.sender_id is None
    assert mapped.is_outgoing is True


def test_internal_read_tool_can_be_called_when_granted() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_SEARCH_CONTACT],
        calls=calls,
        call_results={TYPEX_SEARCH_CONTACT.name: {"match_count": 0, "candidates": []}},
    )
    client = mcp_client(handler, allowed=set())
    client.allow_internal_read_tool(TYPEX_SEARCH_CONTACT.name)
    payload = asyncio.run(client.call_tool(TYPEX_SEARCH_CONTACT.name, {"name": "Affiliate John", "limit": 5}))
    assert payload["match_count"] == 0
    assert TYPEX_SEARCH_CONTACT.name not in client.allowed_tool_names
    assert TYPEX_SEARCH_CONTACT.name in client.internal_read_tool_names


def test_unknown_internal_tool_denied() -> None:
    client = mcp_client(session_handler([TEST_CHAT_TOOL]), allowed=set())
    client.allow_internal_read_tool("typex.not_a_real_tool")
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool("typex.not_a_real_tool", {}))


def test_internal_write_tool_denied() -> None:
    calls: dict[str, list[dict]] = {}
    client = mcp_client(session_handler([TEST_SEND_TOOL], calls=calls, default_call_result=[]), allowed=set())
    client.allow_internal_read_tool(TEST_SEND_TOOL.name)
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool(TEST_SEND_TOOL.name, {}))
    assert calls == {}


def test_discovery_does_not_grant_internal_permission() -> None:
    client = mcp_client(session_handler([TYPEX_SEARCH_CONTACT, TEST_CHAT_TOOL]), allowed=set())
    asyncio.run(client.ensure_session())
    assert TYPEX_SEARCH_CONTACT.name in {item.name for item in client.discovered_tools}
    assert client.internal_read_tool_names == set()
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool(TYPEX_SEARCH_CONTACT.name, {"name": "x"}))
