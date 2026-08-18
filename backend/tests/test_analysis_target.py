import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockAIProvider
from app.enums import ChatType, DirectionSource, MessageDirection, Platform
from app.models import AIAnalysis, Chat, Message
from app.services.analysis import AIAnalysisService
from app.services.analysis_context import build_analysis_context
from app.services.inbox import analysis_target_message, list_chat_summaries
from app.services.message_direction import set_message_direction


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, tzinfo=timezone.utc)


def _chat(session: Session, external_id: str = "tx-actionable") -> Chat:
    chat = Chat(
        platform=Platform.TYPEX,
        external_id=external_id,
        name="Affiliate John",
        chat_type=ChatType.DIRECT,
    )
    session.add(chat)
    session.flush()
    return chat


def _message(
    session: Session,
    chat: Chat,
    *,
    external_id: str,
    hour: int,
    minute: int = 0,
    direction: MessageDirection,
    text: str = "hello",
) -> Message:
    source = (
        DirectionSource.UNKNOWN
        if direction == MessageDirection.UNKNOWN
        else DirectionSource.NATIVE
    )
    message = Message(
        chat_id=chat.id,
        external_id=external_id,
        sender_name="John",
        text=text,
        timestamp=_ts(hour, minute),
        direction=direction,
        direction_source=source,
    )
    session.add(message)
    session.flush()
    return message


def test_target_newer_unknown_over_older_incoming(db_session: Session) -> None:
    chat = _chat(db_session, "a")
    _message(db_session, chat, external_id="in", hour=10, direction=MessageDirection.INCOMING)
    unknown = _message(
        db_session, chat, external_id="unk", hour=11, direction=MessageDirection.UNKNOWN
    )
    db_session.commit()
    target = analysis_target_message(db_session, chat.id)
    assert target is not None
    assert target.id == unknown.id
    assert target.direction is MessageDirection.UNKNOWN


def test_target_newer_incoming_over_older_unknown(db_session: Session) -> None:
    chat = _chat(db_session, "b")
    _message(db_session, chat, external_id="unk", hour=10, direction=MessageDirection.UNKNOWN)
    incoming = _message(
        db_session, chat, external_id="in", hour=11, direction=MessageDirection.INCOMING
    )
    db_session.commit()
    target = analysis_target_message(db_session, chat.id)
    assert target is not None
    assert target.id == incoming.id
    assert target.direction is MessageDirection.INCOMING


def test_target_incoming_when_later_outgoing(db_session: Session) -> None:
    chat = _chat(db_session, "c")
    incoming = _message(
        db_session, chat, external_id="in", hour=10, direction=MessageDirection.INCOMING
    )
    _message(db_session, chat, external_id="out", hour=11, direction=MessageDirection.OUTGOING)
    db_session.commit()
    target = analysis_target_message(db_session, chat.id)
    assert target is not None
    assert target.id == incoming.id
    context = build_analysis_context(db_session, incoming.id)
    assert any(item.direction == MessageDirection.OUTGOING for item in context.recent_messages)


def test_target_none_when_outgoing_only(db_session: Session) -> None:
    chat = _chat(db_session, "d")
    _message(db_session, chat, external_id="out", hour=11, direction=MessageDirection.OUTGOING)
    db_session.commit()
    assert analysis_target_message(db_session, chat.id) is None


def test_target_newest_of_multiple_unknown(db_session: Session) -> None:
    chat = _chat(db_session, "e")
    _message(db_session, chat, external_id="u1", hour=10, direction=MessageDirection.UNKNOWN)
    newest = _message(
        db_session, chat, external_id="u2", hour=11, direction=MessageDirection.UNKNOWN
    )
    db_session.commit()
    target = analysis_target_message(db_session, chat.id)
    assert target is not None
    assert target.id == newest.id


def test_target_same_timestamp_greater_id_wins(db_session: Session) -> None:
    chat = _chat(db_session, "f")
    first = _message(
        db_session, chat, external_id="u1", hour=11, direction=MessageDirection.UNKNOWN
    )
    second = _message(
        db_session, chat, external_id="u2", hour=11, direction=MessageDirection.INCOMING
    )
    db_session.commit()
    assert second.id > first.id
    target = analysis_target_message(db_session, chat.id)
    assert target is not None
    assert target.id == second.id


def test_chat_summary_ai_uses_latest_actionable_not_older_incoming(db_session: Session) -> None:
    chat = _chat(db_session, "summary-stale")
    incoming = _message(
        db_session,
        chat,
        external_id="in",
        hour=10,
        direction=MessageDirection.INCOMING,
        text="Can we increase CPA for Indonesia PWA traffic?",
    )
    unknown = _message(
        db_session,
        chat,
        external_id="unk",
        hour=11,
        direction=MessageDirection.UNKNOWN,
        text="Can you confirm the CPA?",
    )
    db_session.commit()
    service = AIAnalysisService(db_session, MockAIProvider())
    asyncio.run(service.analyze_message(incoming.id))
    db_session.commit()

    summary = next(item for item in list_chat_summaries(db_session) if item.id == chat.id)
    assert summary.ai_priority is None
    assert summary.ai_needs_reply is None
    assert summary.ai_needs_igor is None

    unknown_analysis = asyncio.run(service.analyze_message(unknown.id))
    db_session.commit()
    assert unknown_analysis.needs_reply is True
    assert unknown_analysis.draft_is_provisional is True

    summary = next(item for item in list_chat_summaries(db_session) if item.id == chat.id)
    assert summary.ai_needs_reply is True
    assert summary.ai_priority is not None


def test_direction_change_deletes_analysis_incoming_and_outgoing(db_session: Session) -> None:
    chat = _chat(db_session, "inv-1")
    unknown = _message(
        db_session,
        chat,
        external_id="u",
        hour=11,
        direction=MessageDirection.UNKNOWN,
        text="Can we increase CPA for Indonesia PWA traffic?",
    )
    db_session.commit()
    service = AIAnalysisService(db_session, MockAIProvider())
    asyncio.run(service.analyze_message(unknown.id))
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 1

    set_message_direction(db_session, unknown.id, MessageDirection.INCOMING)
    db_session.commit()
    assert db_session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == unknown.id)) is None

    asyncio.run(service.analyze_message(unknown.id))
    db_session.commit()
    set_message_direction(db_session, unknown.id, MessageDirection.UNKNOWN)
    db_session.commit()
    asyncio.run(service.analyze_message(unknown.id))
    db_session.commit()
    set_message_direction(db_session, unknown.id, MessageDirection.OUTGOING)
    db_session.commit()
    assert db_session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == unknown.id)) is None
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 0


def test_same_direction_patch_keeps_analysis(db_session: Session) -> None:
    chat = _chat(db_session, "inv-noop")
    incoming = _message(
        db_session,
        chat,
        external_id="in",
        hour=10,
        direction=MessageDirection.INCOMING,
        text="Can we increase CPA for Indonesia PWA traffic?",
    )
    db_session.commit()
    service = AIAnalysisService(db_session, MockAIProvider())
    analysis = asyncio.run(service.analyze_message(incoming.id))
    db_session.commit()
    updated = set_message_direction(db_session, incoming.id, MessageDirection.INCOMING)
    db_session.commit()
    assert updated is not None
    assert updated.direction_source is DirectionSource.NATIVE
    kept = db_session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == incoming.id))
    assert kept is not None
    assert kept.id == analysis.id


def test_manual_incoming_after_invalidation_creates_fresh_analysis(db_session: Session) -> None:
    chat = _chat(db_session, "fresh")
    message = _message(
        db_session,
        chat,
        external_id="u",
        hour=11,
        direction=MessageDirection.UNKNOWN,
        text="Can we increase CPA for Indonesia PWA traffic?",
    )
    db_session.commit()
    service = AIAnalysisService(db_session, MockAIProvider())
    first = asyncio.run(service.analyze_message(message.id))
    db_session.commit()
    assert first.needs_reply is True
    assert first.draft_is_provisional is True

    set_message_direction(db_session, message.id, MessageDirection.INCOMING)
    db_session.commit()
    assert db_session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == message.id)) is None

    second = asyncio.run(service.analyze_message(message.id))
    db_session.commit()
    assert second.needs_reply is True
    assert second.draft_reply is not None
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 1


def test_outgoing_override_switches_target_and_keeps_older_analysis(
    api_client: TestClient,
    db_session: Session,
) -> None:
    chat = _chat(db_session, "switch")
    incoming = _message(
        db_session,
        chat,
        external_id="in",
        hour=10,
        direction=MessageDirection.INCOMING,
        text="Can we increase CPA for Indonesia PWA traffic?",
    )
    unknown = _message(
        db_session,
        chat,
        external_id="unk",
        hour=11,
        direction=MessageDirection.UNKNOWN,
        text="Can you confirm the CPA?",
    )
    db_session.commit()
    service = AIAnalysisService(db_session, MockAIProvider())
    incoming_analysis = asyncio.run(service.analyze_message(incoming.id))
    unknown_analysis = asyncio.run(service.analyze_message(unknown.id))
    db_session.commit()
    assert unknown_analysis.draft_is_provisional is True

    patched = api_client.patch(f"/messages/{unknown.id}/direction", json={"direction": "outgoing"})
    assert patched.status_code == 200
    assert patched.json()["direction"] == "outgoing"
    assert patched.json()["direction_source"] == "manual"

    db_session.expire_all()
    assert db_session.get(AIAnalysis, unknown_analysis.id) is None
    kept = db_session.get(AIAnalysis, incoming_analysis.id)
    assert kept is not None
    target = analysis_target_message(db_session, chat.id)
    assert target is not None
    assert target.id == incoming.id

    fetched = api_client.get(f"/chats/{chat.id}/analysis")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == incoming_analysis.id


def test_analyze_outgoing_only_returns_safe_error(api_client: TestClient, db_session: Session) -> None:
    chat = _chat(db_session, "out-only")
    _message(db_session, chat, external_id="out", hour=11, direction=MessageDirection.OUTGOING)
    db_session.commit()
    missing = api_client.get(f"/chats/{chat.id}/analysis")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "No analyzable messages"
    analyze = api_client.post(f"/chats/{chat.id}/analyze")
    assert analyze.status_code == 400
    assert analyze.json()["detail"] == "No analyzable messages"
