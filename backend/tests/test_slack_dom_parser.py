"""Slack DOM parser tests. Fixtures are sanitized and contain no private Slack text."""

from __future__ import annotations

from app.config import PROJECT_ROOT
from app.integrations.slack_dom_parser import (
    conversation_id_from_url,
    fallback_message_id,
    find_canonical_message_roots,
    find_message_pane,
    parse_html,
    parse_slack_dom,
    semantic_fingerprint,
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


def test_one_real_message_is_exactly_one_parsed_message() -> None:
    page = parse_slack_dom(_load("dm-incoming.html"), DM_URL)
    assert len(page.messages) == 1


def test_nested_wrappers_collapse_to_one_root() -> None:
    html = _load("nested-wrappers.html")
    root = parse_html(html)
    pane = find_message_pane(root)
    assert pane is not None
    assert len(find_canonical_message_roots(pane)) == 1
    page = parse_slack_dom(html, CHANNEL_URL)
    assert len(page.messages) == 1
    assert page.messages[0].text == "Need a higher CPA for KR"
    assert page.messages[0].external_id == "1710001100.000100"


def test_virtualized_rerender_keeps_stable_id() -> None:
    first = parse_slack_dom(_load("virtualized-rerender.html"), CHANNEL_URL).messages[0]
    second = parse_slack_dom(_load("virtualized-rerender-b.html"), CHANNEL_URL).messages[0]
    assert first.external_id == second.external_id == "1710002600.000100"
    assert first.text == second.text == "Still on screen"


def test_reaction_does_not_change_text_or_fingerprint() -> None:
    plain = parse_slack_dom(_load("cpa-plain.html"), CHANNEL_URL).messages[0]
    reacted = parse_slack_dom(_load("reaction-added.html"), CHANNEL_URL).messages[0]
    assert reacted.text == "Can you check CPA?"
    assert plain.text == reacted.text
    assert plain.external_id == reacted.external_id
    assert semantic_fingerprint(plain) == semantic_fingerprint(reacted)
    assert "👍" not in reacted.text


def test_hover_toolbar_does_not_enter_body() -> None:
    plain = parse_slack_dom(_load("cpa-plain.html"), CHANNEL_URL).messages[0]
    hovered = parse_slack_dom(_load("hover-toolbar.html"), CHANNEL_URL).messages[0]
    assert hovered.text == "Can you check CPA?"
    assert "Add reaction" not in hovered.text
    assert "Reply" not in hovered.text
    assert "More actions" not in hovered.text
    assert hovered.text == plain.text or hovered.external_id != plain.external_id


def test_thread_count_does_not_change_text() -> None:
    page = parse_slack_dom(_load("thread-count.html"), CHANNEL_URL)
    assert len(page.messages) == 1
    assert page.messages[0].text == "Can you check CPA?"
    assert "replies" not in page.messages[0].text.lower()


def test_explicit_sender_and_grouped_inheritance() -> None:
    page = parse_slack_dom(_load("grouped-continuation.html"), DM_URL)
    assert len(page.messages) == 3
    assert [item.text for item in page.messages] == ["message one", "message two", "message three"]
    assert {item.sender_external_id for item in page.messages} == {"U222AAA"}
    assert {item.sender_name for item in page.messages} == {"Alex Partner"}
    assert {item.direction for item in page.messages} == {"incoming"}
    assert page.messages[0].sender_inherited is False
    assert page.messages[1].sender_inherited is True
    assert page.messages[2].sender_inherited is True


def test_inheritance_stops_at_divider() -> None:
    page = parse_slack_dom(_load("date-unread-dividers.html"), CHANNEL_URL)
    assert [item.text for item in page.messages] == ["before divider", "after divider"]
    assert all(item.text not in {"Today", "New", "Сегодня"} for item in page.messages)
    assert page.messages[0].sender_name == "Alex Partner"
    assert page.messages[1].sender_inherited is False
    assert page.messages[1].sender_name is None


def test_outgoing_and_incoming_stable_ids() -> None:
    page = parse_slack_dom(_load("direction-ids.html"), CHANNEL_URL)
    outgoing, incoming = page.messages
    assert outgoing.direction == "outgoing"
    assert outgoing.sender_external_id == "U_SELF"
    assert incoming.direction == "incoming"
    assert incoming.sender_external_id == "U222AAA"


def test_permalink_timestamp_identity() -> None:
    page = parse_slack_dom(_load("permalink-ts.html"), CHANNEL_URL)
    assert len(page.messages) == 1
    assert page.messages[0].external_id == "1710002200.000300"
    assert page.messages[0].browser_fallback_id is False


def test_low_confidence_garbage_skipped() -> None:
    page = parse_slack_dom(_load("low-confidence-garbage.html"), CHANNEL_URL)
    assert [item.text for item in page.messages] == ["Real message"]
    assert all("Reply" not in item.text and "More actions" not in item.text for item in page.messages)


def test_image_avatar_ignored_and_caption_kept() -> None:
    page = parse_slack_dom(_load("image-with-avatar.html"), CHANNEL_URL)
    assert len(page.messages) == 1
    assert page.messages[0].attachment_placeholder == "image"
    assert page.messages[0].text == "Banner v2 for review\n[Image]"


def test_file_caption_retained() -> None:
    page = parse_slack_dom(_load("file-with-caption.html"), CHANNEL_URL)
    assert page.messages[0].attachment_placeholder == "file"
    assert page.messages[0].text == "Media kit\n[File]"


def test_thread_pane_dedup_and_reply_marker() -> None:
    page = parse_slack_dom(_load("thread-pane.html"), CHANNEL_URL)
    ids = [item.external_id for item in page.messages]
    assert ids == ["1710001900.000100", "1710001901.000200"]
    reply = page.messages[1]
    assert reply.thread_external_id == "1710001900.000100"
    assert reply.text == "Thread reply body"


def test_chronological_dom_order() -> None:
    page = parse_slack_dom(_load("chronological-order.html"), CHANNEL_URL)
    assert [item.text for item in page.messages] == ["alpha", "bravo", "charlie"]


def test_conversation_id_prefers_active_pane_not_url() -> None:
    page = parse_slack_dom(_load("real-style-dm.html"), DM_URL)
    assert page.conversation is not None
    assert page.conversation.external_id == "D0STYLE01"
    assert page.conversation.name == "Alex Partner"
    assert "Direct message" not in page.conversation.name


def test_dm_conversation_id_from_message_permalink() -> None:
    page = parse_slack_dom(_load("dm-permalink-id.html"), "https://app.slack.com/client/T0WORKSPACE")
    assert page.conversation is not None
    assert page.conversation.external_id == "D0PERMDM1"
    assert page.conversation.type == "direct"
    assert page.conversation.name == "Alex Partner"
    assert len(page.messages) == 1
    assert page.messages[0].text == "Need a higher CPA for KR"


def test_conversation_id_ignores_sidebar_and_stale_url() -> None:
    page = parse_slack_dom(_load("sidebar-channel-id.html"), CHANNEL_URL)
    assert page.conversation is not None
    assert page.conversation.external_id == "D0ACTIVE1"
    assert page.conversation.name == "Alex Partner"
    assert len(page.messages) == 1
    assert page.messages[0].text == "Need a higher CPA for KR"


def test_accessibility_duplicate_text_not_in_body() -> None:
    page = parse_slack_dom(_load("accessibility-duplicate.html"), CHANNEL_URL)
    assert len(page.messages) == 1
    assert page.messages[0].text == "Visible body"
    assert page.messages[0].sender_name == "Alex Partner"
    assert page.conversation is not None
    assert page.conversation.name == "offers"


def test_hidden_sender_not_copied_into_body() -> None:
    page = parse_slack_dom(_load("hidden-sender.html"), CHANNEL_URL)
    assert all("Hidden sender" not in item.text for item in page.messages)
    assert page.messages[0].text == "Visible continuation body"
