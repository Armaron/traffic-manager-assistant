import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockAIProvider
from app.enums import AnalysisCategory, ChatType, ConversationStatus, DirectionSource, MessageDirection, Platform, Priority
from app.models import AIAnalysis, Chat, Message
from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult, ImportantEntities
from app.schemas.chat import ChatRead
from app.schemas.message import MessageRead
from app.services.analysis import AIAnalysisService
from app.services.analysis_context import RECENT_MESSAGE_LIMIT, build_analysis_context


def _ts(hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, tzinfo=timezone.utc)


def _add_chat_with_messages(session: Session, texts: list[str]) -> Chat:
    chat = Chat(
        platform=Platform.TYPEX,
        external_id="typex-ctx",
        name="Context Chat",
        chat_type=ChatType.DIRECT,
    )
    session.add(chat)
    session.flush()
    for index, text in enumerate(texts):
        session.add(
            Message(
                chat_id=chat.id,
                external_id=f"m-{index}",
                sender_name="John",
                text=text,
                timestamp=_ts(hour=10) + timedelta(minutes=index),
            )
        )
    session.commit()
    session.refresh(chat)
    return chat


def test_prompt_serializes_unknown_not_as_incoming() -> None:
    from app.ai.prompts import _direction_label, _format_history

    unknown = MessageRead(
        id=1,
        chat_id=1,
        external_id="x",
        sender_external_id=None,
        sender_name="John",
        contact_id=None,
        text="Can you confirm the CPA?",
        timestamp=_ts(),
        direction=MessageDirection.UNKNOWN,
        direction_source=DirectionSource.UNKNOWN,
        is_outgoing=False,
        created_at=_ts(),
    )
    assert _direction_label(unknown) == "UNKNOWN"
    history = _format_history([unknown])
    assert "[UNKNOWN]" in history
    assert "[INCOMING]" not in history

    result = AIAnalysisResult(
        summary="Партнёр спрашивает welcome offer.",
        request="Получить условия welcome offer.",
        category=AnalysisCategory.AFFILIATE,
        priority=Priority.NORMAL,
        needs_reply=True,
        needs_igor=False,
        reason="Can answer from internal knowledge.",
        draft_reply="Hi Jacqueline, sure.",
        important_entities=ImportantEntities(geo=["Indonesia"]),
    )
    assert result.needs_reply is True
    assert result.important_entities.geo == ["Indonesia"]


def test_mock_ai_provider_returns_valid_schema() -> None:
    provider = MockAIProvider()
    context = AIAnalysisContext(
        current_message=MessageRead(
            id=1,
            chat_id=1,
            external_id="x",
            sender_external_id=None,
            sender_name="Eduard",
            contact_id=None,
            text="Can we increase CPA for Indonesia PWA traffic?",
            timestamp=_ts(),
            is_outgoing=False,
            created_at=_ts(),
        ),
        recent_messages=[],
        chat=ChatRead(
            id=1,
            platform=Platform.TELEGRAM,
            external_id="tg",
            name="ReachEffect — Eduard",
            chat_type=ChatType.DIRECT,
            status=ConversationStatus.NEW,
            last_message_at=_ts(),
            created_at=_ts(),
            updated_at=_ts(),
        ),
    )
    result = asyncio.run(provider.analyze_message(context))
    assert isinstance(result, AIAnalysisResult)
    assert result.priority == Priority.HIGH
    assert result.needs_igor is True
    assert result.draft_reply is not None


def test_build_analysis_context_and_recent_limit(db_session: Session) -> None:
    texts = [f"msg {index}" for index in range(25)]
    chat = _add_chat_with_messages(db_session, texts=texts)
    last = db_session.scalars(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.id.desc())
    ).first()
    assert last is not None

    context = build_analysis_context(db_session, last.id)
    assert context.current_message.id == last.id
    assert context.chat.id == chat.id
    assert context.contact is None
    assert context.company is None
    assert len(context.recent_messages) == RECENT_MESSAGE_LIMIT
    timestamps = [item.timestamp for item in context.recent_messages]
    assert timestamps == sorted(timestamps)
    assert context.recent_messages[-1].id == last.id


def test_analyze_message_persists_and_does_not_duplicate(db_session: Session) -> None:
    _add_chat_with_messages(db_session, ["We've started traffic today."])
    message = db_session.scalars(select(Message)).first()
    assert message is not None
    service = AIAnalysisService(db_session, MockAIProvider())

    first = asyncio.run(service.analyze_message(message.id))
    db_session.commit()
    second = asyncio.run(service.analyze_message(message.id))
    db_session.commit()

    assert first.id == second.id
    assert first.priority == Priority.LOW
    assert first.draft_reply is None
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 1


def test_reanalyze_updates_same_row(db_session: Session) -> None:
    _add_chat_with_messages(db_session, ["We've started traffic today."])
    message = db_session.scalars(select(Message)).first()
    assert message is not None
    service = AIAnalysisService(db_session, MockAIProvider())
    first = asyncio.run(service.analyze_message(message.id))
    db_session.commit()
    original_updated = first.updated_at
    message.text = "Can we increase CPA for Indonesia PWA traffic?"
    db_session.commit()

    updated = asyncio.run(service.reanalyze_message(message.id))
    db_session.commit()
    assert updated.id == first.id
    assert updated.priority == Priority.HIGH
    assert updated.needs_igor is True
    assert updated.updated_at >= original_updated
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 1


def test_unknown_direction_summary_blocks_draft(db_session: Session) -> None:
    chat = Chat(
        platform=Platform.TYPEX,
        external_id="tx-unknown",
        name="Affiliate John",
        chat_type=ChatType.DIRECT,
    )
    db_session.add(chat)
    db_session.flush()
    message = Message(
        chat_id=chat.id,
        external_id="u-1",
        sender_name="John",
        text="Can we increase CPA for Indonesia PWA traffic?",
        timestamp=_ts(),
        direction=MessageDirection.UNKNOWN,
        direction_source=DirectionSource.UNKNOWN,
    )
    db_session.add(message)
    db_session.commit()
    service = AIAnalysisService(db_session, MockAIProvider())
    analysis = asyncio.run(service.analyze_message(message.id))
    db_session.commit()
    assert analysis.summary
    assert analysis.draft_reply is None
    assert analysis.needs_reply is False
    assert "Direction confirmation required" in analysis.reason


def test_manual_incoming_allows_normal_draft(db_session: Session) -> None:
    from app.services.message_direction import set_message_direction

    chat = Chat(
        platform=Platform.TYPEX,
        external_id="tx-unknown-2",
        name="Affiliate John",
        chat_type=ChatType.DIRECT,
    )
    db_session.add(chat)
    db_session.flush()
    message = Message(
        chat_id=chat.id,
        external_id="u-2",
        sender_name="John",
        text="Can we increase CPA for Indonesia PWA traffic?",
        timestamp=_ts(),
        direction=MessageDirection.UNKNOWN,
        direction_source=DirectionSource.UNKNOWN,
    )
    db_session.add(message)
    db_session.commit()
    set_message_direction(db_session, message.id, MessageDirection.INCOMING)
    db_session.commit()
    service = AIAnalysisService(db_session, MockAIProvider())
    analysis = asyncio.run(service.analyze_message(message.id))
    db_session.commit()
    assert analysis.needs_reply is True
    assert analysis.draft_reply is not None
