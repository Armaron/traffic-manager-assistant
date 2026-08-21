from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.enums import ChatType, ConversationStatus, DirectionSource, MessageDirection, Platform
from app.integrations.slack_mapping import SlackMessageRecord, map_message, resolve_direction
from app.integrations.slack_self import apply_slack_self_outgoing, is_slack_self_name
from app.models import Chat, Message
from app.schemas.slack_browser import SlackBrowserMessage
from app.services.slack_browser import _direction


def test_name_variants_are_self() -> None:
    assert is_slack_self_name("Igor Amchislavskii")
    assert is_slack_self_name("igor  amchislavski")
    assert is_slack_self_name("Igor Amchislavsky")
    assert is_slack_self_name("Igor Amchislavskiy")
    assert is_slack_self_name("Igor Amchislavskii ") is True
    assert is_slack_self_name("Adam Scott") is False
    assert is_slack_self_name("Igor") is False
    assert is_slack_self_name("Igor Petrov") is False
    assert is_slack_self_name(None) is False


def test_browser_unknown_igor_becomes_outgoing() -> None:
    message = SlackBrowserMessage(
        external_id="1710000900.000100",
        sender_name="Igor Amchislavski",
        timestamp="1710000900.000100",
        text="I'll check with Nick",
        direction="unknown",
    )
    direction, source = _direction(message)
    assert direction is MessageDirection.OUTGOING
    assert source is DirectionSource.PROFILE_NAME


def test_browser_incoming_partner_stays_incoming() -> None:
    message = SlackBrowserMessage(
        external_id="1710000900.000100",
        sender_name="Adam Scott",
        timestamp="1710000900.000100",
        text="invoice",
        direction="incoming",
        sender_external_id="U222",
    )
    direction, source = _direction(message)
    assert direction is MessageDirection.INCOMING
    assert source is DirectionSource.STABLE_ID


def test_official_user_id_still_wins_over_name() -> None:
    mapped = map_message(
        SlackMessageRecord(
            ts="1710000000.000100",
            channel_id="D333",
            chat_name="Eduard",
            chat_type=ChatType.DIRECT,
            user_id="U_OTHER",
            sender_name="Igor Amchislavskii",
            text="hello",
        ),
        current_user_id="U_SELF",
    )
    assert mapped is not None
    assert mapped.direction is MessageDirection.INCOMING
    assert mapped.direction_source is DirectionSource.NATIVE


def test_official_missing_user_id_uses_self_name() -> None:
    direction, source = resolve_direction(
        user_id=None,
        current_user_id="U_SELF",
        sender_name="Igor Amchislavskii",
    )
    assert direction is MessageDirection.OUTGOING
    assert source is DirectionSource.PROFILE_NAME


def test_backfill_upgrades_unknown_and_incoming(db_session: Session) -> None:
    chat = Chat(
        platform=Platform.SLACK,
        external_id="C1",
        name="offers",
        chat_type=ChatType.CHANNEL,
        status=ConversationStatus.NEW,
    )
    db_session.add(chat)
    db_session.flush()
    stamp = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    unknown = Message(
        chat_id=chat.id,
        external_id="1",
        sender_name="Igor Amchislavskii",
        text="sent stats",
        timestamp=stamp,
        direction=MessageDirection.UNKNOWN,
        direction_source=DirectionSource.UNKNOWN,
    )
    incoming = Message(
        chat_id=chat.id,
        external_id="2",
        sender_name="Igor Amchislavski",
        text="ok checking",
        timestamp=stamp,
        direction=MessageDirection.INCOMING,
        direction_source=DirectionSource.NATIVE,
    )
    partner = Message(
        chat_id=chat.id,
        external_id="3",
        sender_name="Adam Scott",
        text="invoice",
        timestamp=stamp,
        direction=MessageDirection.INCOMING,
        direction_source=DirectionSource.NATIVE,
    )
    manual = Message(
        chat_id=chat.id,
        external_id="4",
        sender_name="Igor Amchislavskii",
        text="keep",
        timestamp=stamp,
        direction=MessageDirection.INCOMING,
        direction_source=DirectionSource.MANUAL,
    )
    db_session.add_all([unknown, incoming, partner, manual])
    db_session.flush()
    updated = apply_slack_self_outgoing(db_session)
    assert updated == 2
    db_session.refresh(unknown)
    db_session.refresh(incoming)
    db_session.refresh(partner)
    db_session.refresh(manual)
    assert unknown.direction is MessageDirection.OUTGOING
    assert incoming.direction is MessageDirection.OUTGOING
    assert partner.direction is MessageDirection.INCOMING
    assert manual.direction is MessageDirection.INCOMING
    assert manual.direction_source is DirectionSource.MANUAL
