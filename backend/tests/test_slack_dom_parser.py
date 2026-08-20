"""Slack DOM parser tests. Fixtures are sanitized and contain no private Slack text."""

from __future__ import annotations

from app.config import PROJECT_ROOT
from app.integrations.slack_dom_parser import (
    conversation_id_from_url,
    fallback_message_id,
    parse_slack_dom,
)

FIXTURES = PROJECT_ROOT / "browser-extension" / "slack-reader" / "fixtures"

CHANNEL_URL = "https://app.slack.com/client/T0WORKSPACE/C0OFFERS1"
DM_URL = "https://app.slack.com/client/T0WORKSPACE/D0SAMPLE1"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_incoming_message_parsed() -> None:
    page = parse_slack_dom(_load("dm-incoming.html"), DM_URL)
    assert page.conversation is not None
    assert page.conversation.external_id == "D0SAMPLE1"
    assert page.conversation.type == "direct"
    message = page.messages[0]
    assert message.direction == "incoming"
    assert message.sender_external_id == "U222AAA"
    assert message.text == "Need a higher CPA for KR"
    assert message.browser_fallback_id is False


def test_outgoing_message_parsed() -> None:
    page = parse_slack_dom(_load("channel-outgoing.html"), CHANNEL_URL)
    message = page.messages[0]
    assert message.direction == "outgoing"
    assert message.sender_external_id == "U_SELF"
    assert message.external_id == "1710000910.000200"


def test_unknown_when_self_identity_unavailable() -> None:
    page = parse_slack_dom(_load("unknown-self.html"), CHANNEL_URL)
    assert page.current_user.external_id is None
    assert page.messages[0].direction == "unknown"


def test_stable_external_id() -> None:
    page = parse_slack_dom(_load("dm-incoming.html"), DM_URL)
    assert page.messages[0].external_id == "1710000900.000100"
    assert page.messages[0].browser_fallback_id is False


def test_fallback_deterministic_id() -> None:
    url = "https://app.slack.com/client/T0WORKSPACE/C0FALLBACK"
    page = parse_slack_dom(_load("fallback-id.html"), url)
    message = page.messages[0]
    assert message.browser_fallback_id is True
    assert message.external_id.startswith("b_")
    again = parse_slack_dom(_load("fallback-id.html"), url)
    assert again.messages[0].external_id == message.external_id
    expected = fallback_message_id(
        "C0FALLBACK",
        message.timestamp,
        message.sender_external_id or "",
        message.text,
    )
    assert message.external_id == expected


def test_channel_id_from_url() -> None:
    assert conversation_id_from_url(CHANNEL_URL) == "C0OFFERS1"
    page = parse_slack_dom(_load("channel-outgoing.html"), CHANNEL_URL)
    assert page.conversation is not None
    assert page.conversation.external_id == "C0OFFERS1"
    assert page.conversation.type == "channel"


def test_dm_id_from_url() -> None:
    assert conversation_id_from_url(DM_URL) == "D0SAMPLE1"
    page = parse_slack_dom("<html><body></body></html>", DM_URL)
    assert page.conversation is not None
    assert page.conversation.external_id == "D0SAMPLE1"
    assert page.conversation.type == "direct"


def test_thread_reply() -> None:
    page = parse_slack_dom(_load("thread-reply.html"), CHANNEL_URL)
    message = page.messages[0]
    assert message.thread_external_id == "1710000900.000100"
    assert message.text == "Following up on the cap"


def test_message_edit_retains_id() -> None:
    first = parse_slack_dom(_load("edited-message.html"), CHANNEL_URL).messages[0]
    second = parse_slack_dom(_load("edited-message-rerender.html"), CHANNEL_URL).messages[0]
    assert first.external_id == second.external_id == "1710000940.000500"
    assert second.text == "Updated: CPA can be 1.4"


def test_dom_rerender_does_not_duplicate() -> None:
    first = parse_slack_dom(_load("edited-message.html"), CHANNEL_URL)
    second = parse_slack_dom(_load("edited-message-rerender.html"), CHANNEL_URL)
    ids = [item.external_id for item in first.messages] + [item.external_id for item in second.messages]
    assert ids == ["1710000940.000500", "1710000940.000500"]


def test_image_and_file_placeholders() -> None:
    page = parse_slack_dom(_load("image-file-placeholder.html"), CHANNEL_URL)
    assert page.messages[0].attachment_placeholder == "image"
    assert "[Image]" in page.messages[0].text
    assert page.messages[1].attachment_placeholder == "file"
    assert page.messages[1].text == "[File]"


def test_virtualized_list_only_returns_rendered_nodes() -> None:
    page = parse_slack_dom(_load("virtualized-list.html"), CHANNEL_URL)
    assert [item.external_id for item in page.messages] == ["1710000960.000800"]


def test_visible_deleted_label_is_conservative() -> None:
    page = parse_slack_dom(_load("deleted-visible.html"), CHANNEL_URL)
    assert page.messages[0].deleted is True
    assert page.messages[0].text == "[Deleted Slack message]"


def test_message_list_id_nodes_and_channel_button() -> None:
    page = parse_slack_dom(_load("message-list-ids.html"), CHANNEL_URL)
    assert page.conversation is not None
    assert page.conversation.name == "offers"
    assert len(page.messages) == 1
    message = page.messages[0]
    assert message.external_id == "1710000980.001000"
    assert message.text == "Can we raise the cap?"
    assert message.sender_name == "Alex Partner"


def test_enterprise_client_url() -> None:
    assert (
        conversation_id_from_url("https://app.slack.com/client/E0ENTERPRISE/T0WORKSPACE/C0OFFERS1")
        == "C0OFFERS1"
    )


def test_date_dividers_and_placeholders_are_ignored() -> None:
    page = parse_slack_dom(_load("date-dividers.html"), CHANNEL_URL)
    assert [item.external_id for item in page.messages] == ["1710000990.001100"]
    assert page.messages[0].text == "Need a higher CPA for KR"
    assert all(item.text not in {"Today", "Thursday, February 19th", "Monday, June 1st", "Name and last name"} for item in page.messages)


def test_header_chrome_stripped_from_body() -> None:
    page = parse_slack_dom(_load("chrome-in-body.html"), CHANNEL_URL)
    assert len(page.messages) == 2
    first, second = page.messages
    assert first.sender_name == "Adam Scott"
    assert first.text == "can use anything"
    assert first.attachment_placeholder is None
    assert "[Image]" not in first.text
    assert second.sender_name == "Igor Amchislavski"
    assert second.text == "ok"
    assert second.direction == "outgoing"
