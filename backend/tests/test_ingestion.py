from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ChatType, Platform
from app.models import Chat, Message
from app.schemas.unified import UnifiedChat, UnifiedMessage
from app.services.message_ingestion import MessageIngestionService


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, tzinfo=timezone.utc)


def test_ingest_new_unified_chat(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    chat, created = service.ingest_chat(
        UnifiedChat(
            platform=Platform.TYPEX,
            external_id="typex-affiliate-john",
            name="Affiliate John",
            chat_type=ChatType.DIRECT,
        )
    )
    db_session.commit()

    assert created is True
    assert chat.id is not None
    stored = db_session.get(Chat, chat.id)
    assert stored is not None
    assert stored.platform == Platform.TYPEX
    assert stored.external_id == "typex-affiliate-john"


def test_ingest_new_unified_message(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    message, created = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TELEGRAM,
            external_id="tg-eduard-1",
            chat_id="telegram-reacheffect-eduard",
            chat_name="ReachEffect — Eduard",
            sender_id="tg-user-eduard",
            sender_name="Eduard",
            text="Can we increase CPA for Indonesia PWA traffic?",
            timestamp=_ts(12),
        )
    )
    db_session.commit()

    assert created is True
    stored = db_session.get(Message, message.id)
    assert stored is not None
    assert stored.sender_name == "Eduard"
    assert stored.chat.name == "ReachEffect — Eduard"


def test_repeated_ingestion_does_not_duplicate_message(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    payload = UnifiedMessage(
        platform=Platform.SLACK,
        external_id="slack-jackie-1",
        chat_id="slack-jacqueline",
        chat_name="Jacqueline",
        sender_name="Jacqueline",
        text="Hi Igor",
        timestamp=_ts(15),
    )
    first, first_created = service.ingest_message(payload)
    second, second_created = service.ingest_message(payload)
    db_session.commit()

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    count = db_session.scalar(select(func.count()).select_from(Message))
    assert count == 1


def test_last_message_at_updated(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    older, _ = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="typex-john-1",
            chat_id="typex-affiliate-john",
            chat_name="Affiliate John",
            sender_name="John",
            text="We've started traffic today.",
            timestamp=_ts(10),
        )
    )
    db_session.commit()
    assert older.chat.last_message_at == _ts(10)

    newer, _ = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="typex-john-2",
            chat_id="typex-affiliate-john",
            chat_name="Affiliate John",
            sender_name="John",
            text="I will send the first stats tomorrow.",
            timestamp=_ts(11),
        )
    )
    db_session.commit()
    db_session.refresh(newer.chat)
    assert newer.chat.last_message_at == _ts(11)

    service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="typex-john-0",
            chat_id="typex-affiliate-john",
            chat_name="Affiliate John",
            sender_name="John",
            text="Earlier ping",
            timestamp=_ts(9),
        )
    )
    db_session.commit()
    chat = db_session.scalar(select(Chat).where(Chat.external_id == "typex-affiliate-john"))
    assert chat is not None
    assert chat.last_message_at == _ts(11)


def test_existing_chat_name_not_overwritten_by_message_payload(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    service.ingest_chat(
        UnifiedChat(
            platform=Platform.TYPEX,
            external_id="c1",
            name="Affiliate John",
            chat_type=ChatType.DIRECT,
        )
    )
    db_session.commit()
    service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="m1",
            chat_id="c1",
            chat_name="c1",
            sender_id="john-1",
            sender_name="John",
            text="We've started traffic today.",
            timestamp=_ts(10),
        )
    )
    db_session.commit()
    chat = db_session.scalar(select(Chat).where(Chat.external_id == "c1"))
    assert chat is not None
    assert chat.name == "Affiliate John"
    assert chat.chat_type == ChatType.DIRECT

    service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="m1",
            chat_id="c1",
            chat_name="c1",
            sender_id="john-1",
            sender_name="John",
            text="We've started traffic today.",
            timestamp=_ts(10),
        )
    )
    db_session.commit()
    db_session.refresh(chat)
    assert chat.name == "Affiliate John"
    assert chat.chat_type == ChatType.DIRECT
