"""Slack Desktop Windows notification parser tests. Fixtures contain no real Slack text."""

from __future__ import annotations

import json

from app.config import PROJECT_ROOT
from app.integrations.slack_notification_parser import (
    notification_chat_id,
    parse_slack_notification,
)
from app.integrations.slack_notification_source import (
    BROWSER_UNKNOWN,
    OTHER,
    SLACK_DESKTOP,
    NotificationAppIdentity,
)

FIXTURES = PROJECT_ROOT / "windows-notification-listener" / "fixtures"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _parse(name: str, **overrides: object):
    payload = _load(name)
    payload.update(overrides)
    return parse_slack_notification(
        list(payload["text_elements"]),
        identity=NotificationAppIdentity(
            display_name=str(payload.get("display_name") or "") or None,
            package_family_name=str(payload.get("package_family_name") or "") or None,
            app_user_model_id=str(payload.get("app_user_model_id") or "") or None,
        ),
        notification_id=str(payload.get("notification_id") or "") or None,
        created_at=str(payload.get("created_at") or "") or None,
    )


def test_dm_style_notification_parsed() -> None:
    result = _parse("dm.json")
    assert result.skip_reason is None
    assert result.source_kind == SLACK_DESKTOP
    assert result.sender_name == "Partner A"
    assert result.text == "Can you share current CPA?"
    assert result.conversation_kind == "direct"
    assert result.chat_external_id == "notification:dm:partner-a"
    assert result.notification_external_id.startswith("n_")
    assert result.mapping_confidence in {"high", "medium"}


def test_channel_style_notification_parsed() -> None:
    result = _parse("channel.json")
    assert result.skip_reason is None
    assert result.conversation_kind == "channel"
    assert result.conversation_hint == "acquisition"
    assert result.sender_name == "Partner B"
    assert result.text == "Please check FTD numbers."
    assert result.chat_external_id == "notification:channel:acquisition"
    assert result.mapping_confidence == "high"


def test_multiline_body_preserved() -> None:
    result = _parse("multiline.json")
    assert result.text == "Line one\nLine two"
    assert result.sender_name == "Partner A"


def test_sender_and_conversation_hint_extracted() -> None:
    dm = _parse("dm.json")
    channel = _parse("channel.json")
    assert dm.sender_name == "Partner A"
    assert dm.conversation_hint == "Partner A"
    assert channel.sender_name == "Partner B"
    assert channel.conversation_hint == "acquisition"


def test_aggregate_new_messages_skipped() -> None:
    result = _parse("aggregate.json")
    assert result.skip_reason == "aggregate"
    assert result.text is None
    assert result.chat_external_id is None


def test_generic_unread_skipped() -> None:
    result = _parse("unread.json")
    assert result.skip_reason == "aggregate"
    assert result.text is None


def test_duplicate_notification_same_id() -> None:
    first = _parse("dm.json")
    second = _parse("dm.json")
    assert first.notification_external_id == second.notification_external_id


def test_unrelated_app_discarded() -> None:
    result = _parse("other-app.json")
    assert result.source_kind == OTHER
    assert result.skip_reason == "unrelated"
    assert result.chat_external_id is None


def test_browser_notification_not_ingested_in_v1() -> None:
    result = _parse("browser.json")
    assert result.source_kind == BROWSER_UNKNOWN
    assert result.skip_reason == "browser_unknown"


def test_truncated_indicator() -> None:
    result = _parse("truncated.json")
    assert result.skip_reason is None
    assert result.is_truncated is True
    assert result.text is not None
    assert result.text.endswith("…")


def test_source_classification() -> None:
    assert _parse("dm.json").source_kind == SLACK_DESKTOP
    assert _parse("browser.json").source_kind == BROWSER_UNKNOWN
    assert _parse("other-app.json").source_kind == OTHER


def test_no_stable_slack_id_invented() -> None:
    result = _parse("channel.json")
    assert result.chat_external_id is not None
    assert result.chat_external_id.startswith("notification:")
    assert not result.chat_external_id.startswith(("C", "D", "G"))
    assert result.notification_external_id.startswith("n_")
    assert "C0" not in result.chat_external_id
    namespace = notification_chat_id(kind="direct", hint="Partner A")
    assert namespace == "notification:dm:partner-a"
