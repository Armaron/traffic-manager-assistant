from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ChatType, DirectionSource, MessageDirection, Platform
from app.integrations.typex_resolver import typex_conversation_key, typex_message_key
from app.models import Chat, Message
from app.schemas.unified import UnifiedChat, UnifiedMessage
from app.services.message_ingestion import MessageIngestionService
from app.services.typex_chat_identity import (
    apply_self_profile_name_outgoing,
    merge_typex_duplicate_chats,
    merge_typex_duplicate_messages,
)


def _ts(hour: int = 10) -> datetime:
    return datetime(2026, 8, 17, hour, tzinfo=timezone.utc)


def test_typex_chat_reused_when_opaque_ref_changes(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    first, created_first = service.ingest_chat(
        UnifiedChat(
            platform=Platform.TYPEX,
            external_id="opaque-session-a",
            name="Partner Chat",
            chat_type=ChatType.DIRECT,
        )
    )
    stable = typex_conversation_key(ChatType.DIRECT, "Partner Chat")
    assert stable is not None
    second, created_second = service.ingest_chat(
        UnifiedChat(
            platform=Platform.TYPEX,
            external_id=stable,
            name="Partner Chat",
            chat_type=ChatType.DIRECT,
        )
    )
    db_session.commit()
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert second.external_id == stable
    assert db_session.scalar(select(func.count()).select_from(Chat)) == 1


def test_merge_typex_duplicate_chats_keeps_one_row(db_session: Session) -> None:
    first = Chat(
        platform=Platform.TYPEX,
        external_id="opaque-a",
        name="Partner Chat",
        chat_type=ChatType.DIRECT,
    )
    second = Chat(
        platform=Platform.TYPEX,
        external_id="opaque-b",
        name="Partner Chat",
        chat_type=ChatType.DIRECT,
    )
    telegram = Chat(
        platform=Platform.TELEGRAM,
        external_id="tg-1",
        name="Partner Chat",
        chat_type=ChatType.DIRECT,
    )
    db_session.add_all([first, second, telegram])
    db_session.flush()
    db_session.add_all(
        [
            Message(
                chat_id=first.id,
                external_id="m-shared",
                sender_name="John",
                text="first copy",
                timestamp=_ts(10),
                direction=MessageDirection.UNKNOWN,
                direction_source=DirectionSource.UNKNOWN,
            ),
            Message(
                chat_id=second.id,
                external_id="m-shared",
                sender_name="John",
                text="dup copy",
                timestamp=_ts(10),
                direction=MessageDirection.UNKNOWN,
                direction_source=DirectionSource.UNKNOWN,
            ),
            Message(
                chat_id=second.id,
                external_id="m-only-second",
                sender_name="John",
                text="kept",
                timestamp=_ts(11),
                direction=MessageDirection.UNKNOWN,
                direction_source=DirectionSource.UNKNOWN,
            ),
        ]
    )
    db_session.commit()

    deleted = merge_typex_duplicate_chats(db_session)
    db_session.commit()
    typex_chats = list(
        db_session.scalars(select(Chat).where(Chat.platform == Platform.TYPEX).order_by(Chat.id.asc()))
    )
    assert deleted == 1
    assert len(typex_chats) == 1
    canonical = typex_chats[0]
    assert canonical.external_id == typex_conversation_key(ChatType.DIRECT, "Partner Chat")
    message_ids = list(
        db_session.scalars(select(Message.external_id).where(Message.chat_id == canonical.id).order_by(Message.id))
    )
    assert message_ids == ["m-shared", "m-only-second"]
    assert db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TELEGRAM)) == 1


def test_merge_does_not_rewrite_singleton_typex_chat(db_session: Session) -> None:
    chat = Chat(
        platform=Platform.TYPEX,
        external_id="typex-affiliate-john",
        name="Affiliate John",
        chat_type=ChatType.DIRECT,
    )
    db_session.add(chat)
    db_session.commit()
    deleted = merge_typex_duplicate_chats(db_session)
    db_session.commit()
    db_session.refresh(chat)
    assert deleted == 0
    assert chat.external_id == "typex-affiliate-john"


def test_apply_self_profile_name_marks_outgoing(db_session: Session) -> None:
    chat = Chat(
        platform=Platform.TYPEX,
        external_id="opaque-a",
        name="Partner Chat",
        chat_type=ChatType.DIRECT,
    )
    db_session.add(chat)
    db_session.flush()
    mine = Message(
        chat_id=chat.id,
        external_id="m-self",
        sender_name="Igor - Paid Traffic Manager Am",
        text="sent",
        timestamp=_ts(10),
        direction=MessageDirection.UNKNOWN,
        direction_source=DirectionSource.UNKNOWN,
    )
    other = Message(
        chat_id=chat.id,
        external_id="m-other",
        sender_name="John",
        text="recv",
        timestamp=_ts(11),
        direction=MessageDirection.UNKNOWN,
        direction_source=DirectionSource.UNKNOWN,
    )
    db_session.add_all([mine, other])
    db_session.commit()

    updated = apply_self_profile_name_outgoing(db_session, "Igor - Paid Traffic Manager Am")
    db_session.commit()
    db_session.refresh(mine)
    db_session.refresh(other)
    assert updated == 1
    assert mine.direction is MessageDirection.OUTGOING
    assert mine.direction_source is DirectionSource.PROFILE_NAME
    assert mine.is_outgoing is True
    assert other.direction is MessageDirection.UNKNOWN
    assert other.contact_id is None


def test_reingest_upgrades_unknown_self_message(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    first, created_first = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="m-self",
            chat_id="opaque-a",
            chat_name="Partner Chat",
            sender_name="Igor - Paid Traffic Manager Am",
            text="sent",
            timestamp=_ts(10),
            direction=MessageDirection.UNKNOWN,
            direction_source=DirectionSource.UNKNOWN,
        )
    )
    second, created_second = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="m-self",
            chat_id="opaque-a",
            chat_name="Partner Chat",
            sender_name="Igor - Paid Traffic Manager Am",
            text="sent",
            timestamp=_ts(10),
            direction=MessageDirection.OUTGOING,
            direction_source=DirectionSource.PROFILE_NAME,
        )
    )
    db_session.commit()
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert second.direction is MessageDirection.OUTGOING
    assert second.direction_source is DirectionSource.PROFILE_NAME
    assert second.is_outgoing is True
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_typex_message_reused_when_message_ref_changes(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    first, created_first = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="ref-session-a",
            chat_id="txc:direct:Partner Chat",
            chat_name="Partner Chat",
            sender_name="John",
            text="same body",
            timestamp=_ts(10),
            direction=MessageDirection.UNKNOWN,
            direction_source=DirectionSource.UNKNOWN,
        )
    )
    second, created_second = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="ref-session-b",
            chat_id="txc:direct:Partner Chat",
            chat_name="Partner Chat",
            sender_name="John",
            text="same body",
            timestamp=_ts(10),
            direction=MessageDirection.UNKNOWN,
            direction_source=DirectionSource.UNKNOWN,
        )
    )
    db_session.commit()
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_merge_typex_duplicate_messages_keeps_one_row(db_session: Session) -> None:
    chat = Chat(
        platform=Platform.TYPEX,
        external_id="opaque-a",
        name="Partner Chat",
        chat_type=ChatType.DIRECT,
    )
    telegram = Chat(
        platform=Platform.TELEGRAM,
        external_id="tg-1",
        name="Partner Chat",
        chat_type=ChatType.DIRECT,
    )
    db_session.add_all([chat, telegram])
    db_session.flush()
    db_session.add_all(
        [
            Message(
                chat_id=chat.id,
                external_id="ref-1",
                sender_name="John",
                text="same body",
                timestamp=_ts(10),
                direction=MessageDirection.UNKNOWN,
                direction_source=DirectionSource.UNKNOWN,
            ),
            Message(
                chat_id=chat.id,
                external_id="ref-2",
                sender_name="John",
                text="same body",
                timestamp=_ts(10),
                direction=MessageDirection.OUTGOING,
                direction_source=DirectionSource.PROFILE_NAME,
            ),
            Message(
                chat_id=chat.id,
                external_id="ref-3",
                sender_name="John",
                text="same body",
                timestamp=_ts(10),
                direction=MessageDirection.UNKNOWN,
                direction_source=DirectionSource.UNKNOWN,
            ),
            Message(
                chat_id=chat.id,
                external_id="ref-other",
                sender_name="John",
                text="different body",
                timestamp=_ts(10),
                direction=MessageDirection.UNKNOWN,
                direction_source=DirectionSource.UNKNOWN,
            ),
            Message(
                chat_id=telegram.id,
                external_id="1",
                sender_name="John",
                text="same body",
                timestamp=_ts(10),
            ),
        ]
    )
    db_session.commit()

    deleted = merge_typex_duplicate_messages(db_session)
    db_session.commit()
    typex_messages = list(
        db_session.scalars(select(Message).where(Message.chat_id == chat.id).order_by(Message.id.asc()))
    )
    assert deleted == 2
    assert len(typex_messages) == 2
    kept = typex_messages[0]
    assert kept.text == "same body"
    assert kept.direction is MessageDirection.OUTGOING
    assert kept.external_id == typex_message_key(_ts(10), "John", "same body")
    assert typex_messages[1].text == "different body"
    assert db_session.scalar(select(func.count()).select_from(Message).where(Message.chat_id == telegram.id)) == 1


def test_merge_does_not_rewrite_singleton_typex_message(db_session: Session) -> None:
    chat = Chat(
        platform=Platform.TYPEX,
        external_id="typex-affiliate-john",
        name="Affiliate John",
        chat_type=ChatType.DIRECT,
    )
    db_session.add(chat)
    db_session.flush()
    message = Message(
        chat_id=chat.id,
        external_id="typex-john-1",
        sender_name="John",
        text="We've started traffic today.",
        timestamp=_ts(10),
    )
    db_session.add(message)
    db_session.commit()
    deleted = merge_typex_duplicate_messages(db_session)
    db_session.commit()
    db_session.refresh(message)
    assert deleted == 0
    assert message.external_id == "typex-john-1"
