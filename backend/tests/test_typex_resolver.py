import asyncio

import pytest

from app.enums import ChatType
from app.integrations.typex_errors import TypeXToolUnavailableError
from app.integrations.typex_mapping import map_chat
from app.integrations.typex_resolver import (
    build_resolver_arguments,
    select_exact_handle,
    stable_handle_from_item,
)
from tests.typex_helpers import (
    TYPEX_GET_ME,
    TYPEX_LIST_FOLDER_FEEDS,
    TYPEX_SEARCH_CHAT_RECORDS,
    TYPEX_SEARCH_CONTACT,
    TYPEX_SEND_MESSAGE,
    session_handler,
    typex_adapter,
)

DIRECT_FEED = {
    "name": "Affiliate John",
    "last_message_send_at": "2026-08-17T10:00:00Z",
    "chat_type": 1,
    "chat_type_label": "single chat",
}
GROUP_FEED = {
    "name": "Ops Room",
    "last_message_send_at": "2026-08-17T10:00:00Z",
    "chat_type": 2,
    "chat_type_label": "group chat",
}


def test_unique_exact_contact_result_accepted() -> None:
    handle = select_exact_handle(
        DIRECT_FEED,
        [{"name": "Affiliate John", "ret_type": "contact", "opaque_ref": "ref-contact-1"}],
    )
    assert handle == "ref-contact-1"


def test_unique_exact_group_result_accepted() -> None:
    handle = select_exact_handle(
        GROUP_FEED,
        [{"name": "Ops Room", "ret_type": "feed", "opaque_ref": "ref-group-1"}],
    )
    assert handle == "ref-group-1"


def test_fuzzy_result_rejected() -> None:
    handle = select_exact_handle(
        DIRECT_FEED,
        [{"name": "Affiliate", "ret_type": "contact", "opaque_ref": "ref-1"}],
    )
    assert handle is None


def test_duplicate_exact_names_rejected() -> None:
    handle = select_exact_handle(
        DIRECT_FEED,
        [
            {"name": "Affiliate John", "ret_type": "contact", "opaque_ref": "ref-a"},
            {"name": "Affiliate John", "ret_type": "contact", "opaque_ref": "ref-b"},
        ],
    )
    assert handle is None


def test_type_mismatch_rejected() -> None:
    handle = select_exact_handle(
        DIRECT_FEED,
        [{"name": "Affiliate John", "ret_type": "feed", "opaque_ref": "ref-1"}],
    )
    assert handle is None
    handle = select_exact_handle(
        GROUP_FEED,
        [{"name": "Ops Room", "ret_type": "contact", "opaque_ref": "ref-1"}],
    )
    assert handle is None


def test_missing_opaque_ref_rejected() -> None:
    handle = select_exact_handle(
        DIRECT_FEED,
        [{"name": "Affiliate John", "ret_type": "contact", "typex_id": "JohnID"}],
    )
    assert handle is None


def test_opaque_ref_equal_to_display_name_rejected() -> None:
    handle = select_exact_handle(
        DIRECT_FEED,
        [{"name": "Affiliate John", "ret_type": "contact", "opaque_ref": "Affiliate John"}],
    )
    assert handle is None
    assert stable_handle_from_item({"opaque_ref": "Affiliate John"}, "Affiliate John") is None


def test_same_name_direct_and_group_disambiguated_by_type() -> None:
    mixed = [
        {"name": "Shared", "ret_type": "contact", "opaque_ref": "ref-direct"},
        {"name": "Shared", "ret_type": "feed", "opaque_ref": "ref-group"},
    ]
    direct = {**DIRECT_FEED, "name": "Shared"}
    group = {**GROUP_FEED, "name": "Shared"}
    assert select_exact_handle(direct, mixed) == "ref-direct"
    assert select_exact_handle(group, mixed) == "ref-group"


def test_direct_group_resolver_arguments_are_separated() -> None:
    contact_args = build_resolver_arguments(DIRECT_FEED)
    group_args = build_resolver_arguments(GROUP_FEED)
    assert contact_args == {"name": "Affiliate John", "limit": 5, "search_contact": True}
    assert group_args == {"name": "Ops Room", "limit": 5, "search_group": True}
    assert "search_group" not in contact_args
    assert "search_contact" not in group_args


def test_unknown_chat_type_is_unresolved() -> None:
    assert (
        select_exact_handle(
            {"name": "Mystery", "chat_type": 9, "chat_type_label": "secret"},
            [{"name": "Mystery", "ret_type": "contact", "opaque_ref": "ref-1"}],
        )
        is None
    )


def test_feed_without_handle_remains_unmapped() -> None:
    assert map_chat(DIRECT_FEED) is None


def test_whitespace_normalization_still_exact() -> None:
    handle = select_exact_handle(
        {**DIRECT_FEED, "name": "  Affiliate John  "},
        [{"name": "Affiliate John", "ret_type": "contact", "opaque_ref": "ref-1"}],
    )
    assert handle == "ref-1"


def test_adapter_resolves_feed_to_opaque_ref_and_scopes_messages() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_LIST_FOLDER_FEEDS, TYPEX_SEARCH_CONTACT, TYPEX_SEARCH_CHAT_RECORDS, TYPEX_GET_ME, TYPEX_SEND_MESSAGE],
        calls=calls,
        call_results={
            TYPEX_LIST_FOLDER_FEEDS.name: [DIRECT_FEED],
            TYPEX_SEARCH_CONTACT.name: {
                "ok": True,
                "match_count": 1,
                "candidates": [
                    {"name": "Affiliate John", "ret_type": "contact", "opaque_ref": "ref-contact-1"}
                ],
            },
            TYPEX_SEARCH_CHAT_RECORDS.name: [
                {
                    "message_ref": "msg-1",
                    "sender_id": "u-1",
                    "content": "hello",
                    "send_time": "2026-08-17T10:00:00Z",
                    "is_outgoing": False,
                }
            ],
            TYPEX_GET_ME.name: {"ok": True, "me": {"id": "acct-1", "name": "Operator"}},
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=TYPEX_GET_ME.name,
    )
    chats = asyncio.run(adapter.get_chats())
    assert len(chats) == 1
    assert chats[0].external_id == "ref-contact-1"
    assert chats[0].name == "Affiliate John"
    assert chats[0].chat_type == ChatType.DIRECT
    messages = asyncio.run(adapter.get_messages("ref-contact-1"))
    assert [item.external_id for item in messages] == ["msg-1"]
    assert calls[TYPEX_SEARCH_CONTACT.name][0] == {
        "name": "Affiliate John",
        "limit": 5,
        "search_contact": True,
    }
    assert calls[TYPEX_SEARCH_CHAT_RECORDS.name][0] == {"opaque_ref": "ref-contact-1", "limit": 50}
    assert "query" not in calls[TYPEX_SEARCH_CHAT_RECORDS.name][0]
    assert "contact_name" not in calls[TYPEX_SEARCH_CHAT_RECORDS.name][0]
    assert TYPEX_SEND_MESSAGE.name not in calls


def test_adapter_skips_unresolved_feed_and_does_not_fabricate_id() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_LIST_FOLDER_FEEDS, TYPEX_SEARCH_CONTACT, TYPEX_SEARCH_CHAT_RECORDS],
        calls=calls,
        call_results={
            TYPEX_LIST_FOLDER_FEEDS.name: [DIRECT_FEED],
            TYPEX_SEARCH_CONTACT.name: {
                "ok": True,
                "candidates": [{"name": "Someone Else", "ret_type": "contact", "opaque_ref": "ref-other"}],
            },
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=None,
    )
    chats = asyncio.run(adapter.get_chats())
    assert chats == []
    assert TYPEX_SEARCH_CHAT_RECORDS.name not in calls


def test_adapter_group_feed_uses_search_group_flag() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_LIST_FOLDER_FEEDS, TYPEX_SEARCH_CONTACT, TYPEX_SEARCH_CHAT_RECORDS],
        calls=calls,
        call_results={
            TYPEX_LIST_FOLDER_FEEDS.name: [GROUP_FEED],
            TYPEX_SEARCH_CONTACT.name: {
                "ok": True,
                "candidates": [{"name": "Ops Room", "ret_type": "feed", "opaque_ref": "ref-group-1"}],
            },
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=None,
    )
    chats = asyncio.run(adapter.get_chats())
    assert chats[0].external_id == "ref-group-1"
    assert chats[0].chat_type == ChatType.GROUP
    assert calls[TYPEX_SEARCH_CONTACT.name][0]["search_group"] is True
    assert "search_contact" not in calls[TYPEX_SEARCH_CONTACT.name][0]


def test_resolver_does_not_call_write_tools() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler(
        [TYPEX_LIST_FOLDER_FEEDS, TYPEX_SEARCH_CONTACT, TYPEX_SEARCH_CHAT_RECORDS, TYPEX_SEND_MESSAGE],
        calls=calls,
        call_results={
            TYPEX_LIST_FOLDER_FEEDS.name: [DIRECT_FEED],
            TYPEX_SEARCH_CONTACT.name: {
                "candidates": [{"name": "Affiliate John", "ret_type": "contact", "opaque_ref": "ref-1"}]
            },
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=None,
    )
    asyncio.run(adapter.get_chats())
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(adapter._client.call_tool(TYPEX_SEND_MESSAGE.name, {}))
    assert TYPEX_SEND_MESSAGE.name not in calls
