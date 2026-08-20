from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import (
    AnalysisCategory,
    ChatType,
    CompanyType,
    ConversationStatus,
    Platform,
    Priority,
)
from app.models import AIAnalysis, Chat, Message
from app.schemas.chat import ChatRead
from app.schemas.message import MessageRead


def _utc(year: int = 2026, month: int = 8, day: int = 17, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _make_chat(external_id: str = "chat-1", name: str = "ReachEffect") -> Chat:
    return Chat(
        platform=Platform.TYPEX,
        external_id=external_id,
        name=name,
        chat_type=ChatType.DIRECT,
        status=ConversationStatus.NEW,
    )


def test_models_create_tables(db_engine) -> None:
    tables = set(inspect(db_engine).get_table_names())
    assert {
        "companies",
        "contacts",
        "contact_identities",
        "chats",
        "messages",
        "knowledge_entries",
        "ai_analyses",
        "message_translations",
    }.issubset(tables)


def test_chat_can_be_created(db_session: Session) -> None:
    chat = _make_chat()
    db_session.add(chat)
    db_session.commit()

    stored = db_session.get(Chat, chat.id)
    assert stored is not None
    assert stored.platform == Platform.TYPEX
    assert stored.external_id == "chat-1"
    assert ChatRead.model_validate(stored).name == "ReachEffect"


def test_message_can_be_created(db_session: Session) -> None:
    chat = _make_chat()
    db_session.add(chat)
    db_session.commit()

    message = Message(
        chat_id=chat.id,
        external_id="msg-1",
        sender_name="Eduard",
        text="Can we increase CPA for ID traffic to $25?",
        timestamp=_utc(),
    )
    db_session.add(message)
    db_session.commit()

    stored = db_session.get(Message, message.id)
    assert stored is not None
    assert stored.chat_id == chat.id
    assert stored.timestamp.tzinfo is not None
    assert MessageRead.model_validate(stored).external_id == "msg-1"


def test_chat_messages_relationship(db_session: Session) -> None:
    chat = _make_chat()
    chat.messages.append(
        Message(
            external_id="msg-1",
            sender_name="Eduard",
            text="First",
            timestamp=_utc(),
        )
    )
    chat.messages.append(
        Message(
            external_id="msg-2",
            sender_name="Eduard",
            text="Second",
            timestamp=_utc(hour=13),
        )
    )
    db_session.add(chat)
    db_session.commit()

    stored = db_session.get(Chat, chat.id)
    assert stored is not None
    assert len(stored.messages) == 2
    assert {item.external_id for item in stored.messages} == {"msg-1", "msg-2"}


def test_duplicate_message_in_same_chat_rejected(db_session: Session) -> None:
    chat = _make_chat()
    db_session.add(chat)
    db_session.commit()

    db_session.add(
        Message(
            chat_id=chat.id,
            external_id="msg-dup",
            text="Hello",
            timestamp=_utc(),
        )
    )
    db_session.commit()

    db_session.add(
        Message(
            chat_id=chat.id,
            external_id="msg-dup",
            text="Hello again",
            timestamp=_utc(hour=14),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    other_chat = _make_chat(external_id="chat-2", name="Internal")
    db_session.add(other_chat)
    db_session.commit()
    db_session.add(
        Message(
            chat_id=other_chat.id,
            external_id="msg-dup",
            text="Same external id, different chat",
            timestamp=_utc(),
        )
    )
    db_session.commit()
    assert db_session.query(Message).count() == 2


def test_duplicate_chat_platform_external_id_rejected(db_session: Session) -> None:
    db_session.add(_make_chat())
    db_session.commit()

    db_session.add(_make_chat(name="Copy"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    db_session.add(
        Chat(
            platform=Platform.SLACK,
            external_id="chat-1",
            name="Slack copy",
            chat_type=ChatType.DIRECT,
            status=ConversationStatus.NEW,
        )
    )
    db_session.commit()
    assert db_session.query(Chat).count() == 2


def test_ai_analysis_one_to_one_with_message(db_session: Session) -> None:
    chat = _make_chat()
    message = Message(
        external_id="msg-ai",
        sender_name="Eduard",
        text="Please confirm CPA",
        timestamp=_utc(),
    )
    chat.messages.append(message)
    db_session.add(chat)
    db_session.commit()

    analysis = AIAnalysis(
        message_id=message.id,
        summary="Partner asks to raise Indonesia CPA.",
        request="Approval for CPA $25",
        category=AnalysisCategory.AFFILIATE,
        priority=Priority.HIGH,
        needs_reply=True,
        needs_igor=True,
        reason="CPA change needs internal approval.",
        draft_reply="Let me confirm internally.",
        provider="mock",
        model="mock-v1",
    )
    db_session.add(analysis)
    db_session.commit()

    stored_message = db_session.get(Message, message.id)
    assert stored_message is not None
    assert stored_message.analysis is not None
    assert stored_message.analysis.id == analysis.id
    assert analysis.message.id == message.id

    db_session.add(
        AIAnalysis(
            message_id=message.id,
            summary="Duplicate",
            request="Duplicate",
            category=AnalysisCategory.OTHER,
            priority=Priority.LOW,
            needs_reply=False,
            needs_igor=False,
            reason="Should fail",
            draft_reply="",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_company_type_values_are_stored() -> None:
    assert CompanyType.AFFILIATE.value == "affiliate"
    assert CompanyType.AD_NETWORK.value == "ad_network"
