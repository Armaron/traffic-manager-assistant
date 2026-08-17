from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import Platform
from app.models import Contact, ContactIdentity, Message
from app.schemas.unified import UnifiedMessage
from app.services.message_ingestion import MessageIngestionService


def _ts(hour: int) -> datetime:
    return datetime(2026, 8, 17, hour, tzinfo=timezone.utc)


def test_typex_message_creates_contact_identity(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    message, created = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="tx-m-1",
            chat_id="tx-john",
            chat_name="Affiliate John",
            sender_id="tx-user-john",
            sender_name="John",
            text="We've started traffic today.",
            timestamp=_ts(10),
        )
    )
    db_session.commit()
    assert created is True
    assert message.contact_id is not None
    contact = db_session.get(Contact, message.contact_id)
    assert contact is not None
    assert contact.name == "John"
    identity = db_session.scalar(
        select(ContactIdentity).where(
            ContactIdentity.platform == Platform.TYPEX,
            ContactIdentity.external_user_id == "tx-user-john",
        )
    )
    assert identity is not None
    assert identity.contact_id == contact.id


def test_second_message_reuses_contact(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    first, _ = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="tx-m-1",
            chat_id="tx-john",
            chat_name="Affiliate John",
            sender_id="tx-user-john",
            sender_name="John",
            text="We've started traffic today.",
            timestamp=_ts(10),
        )
    )
    second, created = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="tx-m-2",
            chat_id="tx-john",
            chat_name="Affiliate John",
            sender_id="tx-user-john",
            sender_name="John",
            text="I will send the first stats tomorrow.",
            timestamp=_ts(11),
        )
    )
    db_session.commit()
    assert created is True
    assert first.contact_id == second.contact_id
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 1
    assert db_session.scalar(select(func.count()).select_from(ContactIdentity)) == 1
    assert second.chat.last_message_at == _ts(11)


def test_duplicate_sync_does_not_duplicate_messages(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    payload = UnifiedMessage(
        platform=Platform.TYPEX,
        external_id="tx-m-1",
        chat_id="tx-john",
        chat_name="Affiliate John",
        sender_id="tx-user-john",
        sender_name="John",
        text="We've started traffic today.",
        timestamp=_ts(10),
    )
    first, first_created = service.ingest_message(payload)
    second, second_created = service.ingest_message(payload)
    db_session.commit()
    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 1


def test_same_external_id_other_platform_does_not_collide(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    typex, _ = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="m-1",
            chat_id="tx-1",
            chat_name="TypeX user",
            sender_id="shared-id",
            sender_name="Alex",
            text="TypeX ping",
            timestamp=_ts(10),
        )
    )
    slack, _ = service.ingest_message(
        UnifiedMessage(
            platform=Platform.SLACK,
            external_id="m-1",
            chat_id="slack-1",
            chat_name="Slack user",
            sender_id="shared-id",
            sender_name="Alex",
            text="Slack ping",
            timestamp=_ts(11),
        )
    )
    db_session.commit()
    assert typex.contact_id != slack.contact_id
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 2
    assert db_session.scalar(select(func.count()).select_from(ContactIdentity)) == 2
