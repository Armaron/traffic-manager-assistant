from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.upgrade import apply_schema_upgrades
from app.enums import DirectionSource, MessageDirection, Platform
from app.models import Contact, Message
from app.schemas.unified import UnifiedMessage
from app.services.message_direction import set_message_direction
from app.services.message_ingestion import MessageIngestionService


def _ts() -> datetime:
    return datetime(2026, 8, 17, 10, 42, tzinfo=timezone.utc)


def test_schema_upgrade_backfills_legacy_is_outgoing() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE chats (id INTEGER PRIMARY KEY, platform VARCHAR(32), "
                "external_id VARCHAR(255), name VARCHAR(255), chat_type VARCHAR(32), "
                "status VARCHAR(32), last_message_at DATETIME, created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    external_id VARCHAR(255),
                    sender_external_id VARCHAR(255),
                    sender_name VARCHAR(255),
                    contact_id INTEGER,
                    text TEXT,
                    timestamp DATETIME,
                    is_outgoing BOOLEAN,
                    raw_data JSON,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO chats (id, platform, external_id, name, chat_type, status) "
                "VALUES (1, 'typex', 'c1', 'John', 'direct', 'NEW')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO messages (id, chat_id, external_id, text, timestamp, is_outgoing) "
                "VALUES (1, 1, 'out', 'sent', '2026-08-17T10:00:00', 1), "
                "(2, 1, 'in', 'recv', '2026-08-17T10:01:00', 0)"
            )
        )
    apply_schema_upgrades(engine)
    apply_schema_upgrades(engine)
    with engine.connect() as connection:
        rows = list(
            connection.execute(
                text("SELECT external_id, direction, direction_source, is_outgoing FROM messages ORDER BY id")
            )
        )
    assert rows[0] == ("out", "outgoing", "native", 1)
    assert rows[1] == ("in", "incoming", "native", 0)
    engine.dispose()


def test_unknown_message_persists_without_contact(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    message, created = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="msg-1",
            chat_id="ref-1",
            chat_name="Affiliate John",
            sender_id=None,
            sender_name="John",
            text="Can you confirm the CPA?",
            timestamp=_ts(),
            direction=MessageDirection.UNKNOWN,
            direction_source=DirectionSource.UNKNOWN,
        )
    )
    db_session.commit()
    assert created is True
    assert message.direction is MessageDirection.UNKNOWN
    assert message.sender_name == "John"
    assert message.sender_external_id is None
    assert message.contact_id is None
    assert message.is_outgoing is False
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_unknown_duplicate_not_created(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    payload = UnifiedMessage(
        platform=Platform.TYPEX,
        external_id="msg-1",
        chat_id="ref-1",
        chat_name="Affiliate John",
        sender_name="John",
        text="hello",
        timestamp=_ts(),
        direction=MessageDirection.UNKNOWN,
        direction_source=DirectionSource.UNKNOWN,
    )
    first, first_created = service.ingest_message(payload)
    second, second_created = service.ingest_message(payload)
    db_session.commit()
    assert first_created is True
    assert second_created is False
    assert first.id == second.id


def test_manual_override_unknown_to_incoming_does_not_create_contact(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    stored, _ = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="msg-1",
            chat_id="ref-1",
            chat_name="Affiliate John",
            sender_name="John",
            text="hello",
            timestamp=_ts(),
            direction=MessageDirection.UNKNOWN,
            direction_source=DirectionSource.UNKNOWN,
        )
    )
    db_session.commit()
    updated = set_message_direction(db_session, stored.id, MessageDirection.INCOMING)
    db_session.commit()
    assert updated is not None
    assert updated.direction is MessageDirection.INCOMING
    assert updated.direction_source is DirectionSource.MANUAL
    assert updated.contact_id is None
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 0


def test_manual_override_unknown_to_outgoing_no_self_contact(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    stored, _ = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="msg-1",
            chat_id="ref-1",
            chat_name="Affiliate John",
            sender_name="John",
            text="hello",
            timestamp=_ts(),
            direction=MessageDirection.UNKNOWN,
            direction_source=DirectionSource.UNKNOWN,
        )
    )
    db_session.commit()
    updated = set_message_direction(db_session, stored.id, MessageDirection.OUTGOING)
    db_session.commit()
    assert updated is not None
    assert updated.direction is MessageDirection.OUTGOING
    assert updated.is_outgoing is True
    assert updated.contact_id is None
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 0
