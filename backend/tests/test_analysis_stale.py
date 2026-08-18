"""Stale AI analysis is chronology of messages, not analysis created_at, and never auto-calls AI."""

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockAIProvider
from app.enums import ChatType, DirectionSource, MessageDirection, Platform
from app.models import AIAnalysis, Chat, Message
from app.services.analysis import AIAnalysisService
from app.services.inbox import analysis_is_stale, analysis_staleness, latest_chat_analysis


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, tzinfo=timezone.utc)


def _chat(session: Session, external_id: str = "stale-chat") -> Chat:
    chat = Chat(
        platform=Platform.TYPEX,
        external_id=external_id,
        name="Affiliate",
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
    direction: MessageDirection = MessageDirection.INCOMING,
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


def _analyze(session: Session, message_id: int) -> AIAnalysis:
    service = AIAnalysisService(session, MockAIProvider())
    row = asyncio.run(service.analyze_message(message_id))
    session.commit()
    return row


def test_no_later_messages_is_not_stale(db_session: Session) -> None:
    chat = _chat(db_session, "fresh")
    target = _message(db_session, chat, external_id="in-1000", hour=10, text="Can you increase CPA?")
    analysis = _analyze(db_session, target.id)

    stale = analysis_staleness(db_session, analysis)
    assert stale.is_stale is False
    assert stale.newer_messages_count == 0
    assert stale.latest_message_id == target.id
    assert analysis_is_stale(db_session, analysis) is False


def test_later_incoming_makes_analysis_stale(api_client: TestClient, db_session: Session) -> None:
    chat = _chat(db_session, "later-in")
    target = _message(db_session, chat, external_id="in-1000", hour=10, text="Can you increase CPA?")
    analysis = _analyze(db_session, target.id)
    later = _message(db_session, chat, external_id="in-1005", hour=10, minute=5, text="ok thanks")
    db_session.commit()

    payload = api_client.get(f"/chats/{chat.id}/analysis").json()
    assert payload["id"] == analysis.id
    assert payload["is_stale"] is True
    assert payload["newer_messages_count"] == 1
    assert payload["latest_message_id"] == later.id
    assert db_session.get(AIAnalysis, analysis.id) is not None


def test_later_outgoing_makes_analysis_stale(api_client: TestClient, db_session: Session) -> None:
    chat = _chat(db_session, "later-out")
    target = _message(db_session, chat, external_id="in-1000", hour=10, text="Can you increase CPA?")
    analysis = _analyze(db_session, target.id)
    _message(
        db_session,
        chat,
        external_id="out-1005",
        hour=10,
        minute=5,
        direction=MessageDirection.OUTGOING,
        text="Approved, $25 is fine.",
    )
    db_session.commit()

    payload = api_client.get(f"/chats/{chat.id}/analysis").json()
    assert payload["id"] == analysis.id
    assert payload["is_stale"] is True
    assert payload["newer_messages_count"] == 1
    assert payload["draft_reply"]  # old draft is kept, only marked stale


def test_same_timestamp_higher_id_is_stale(db_session: Session) -> None:
    chat = _chat(db_session, "tie")
    first = _message(db_session, chat, external_id="m-100", hour=10, text="first")
    second = _message(db_session, chat, external_id="m-101", hour=10, text="second")
    assert first.timestamp == second.timestamp
    assert second.id > first.id
    analysis = _analyze(db_session, first.id)

    stale = analysis_staleness(db_session, analysis)
    assert stale.is_stale is True
    assert stale.newer_messages_count == 1
    assert stale.latest_message_id == second.id


def test_older_timestamp_inserted_later_is_not_stale(db_session: Session) -> None:
    chat = _chat(db_session, "backfill")
    target = _message(db_session, chat, external_id="in-1000", hour=10, text="target")
    analysis = _analyze(db_session, target.id)
    older = _message(db_session, chat, external_id="in-0900", hour=9, text="older, ingested later")
    db_session.commit()
    assert older.id > target.id

    stale = analysis_staleness(db_session, analysis)
    assert stale.is_stale is False
    assert stale.newer_messages_count == 0
    assert stale.latest_message_id == target.id


def test_new_analysis_on_latest_is_not_stale(api_client: TestClient, db_session: Session) -> None:
    chat = _chat(db_session, "clears")
    first = _message(db_session, chat, external_id="in-1000", hour=10, text="Can you increase CPA?")
    old = _analyze(db_session, first.id)
    later = _message(db_session, chat, external_id="in-1005", hour=10, minute=5, text="and GEO?")
    db_session.commit()

    stale = api_client.get(f"/chats/{chat.id}/analysis").json()
    assert stale["id"] == old.id
    assert stale["is_stale"] is True

    fresh = api_client.post(f"/chats/{chat.id}/reanalyze")
    assert fresh.status_code == 200
    payload = fresh.json()
    assert payload["message_id"] == later.id
    assert payload["is_stale"] is False
    assert payload["newer_messages_count"] == 0
    assert db_session.get(AIAnalysis, old.id) is not None


def test_race_new_message_before_persist_marks_stale(api_client: TestClient, db_session: Session) -> None:
    chat = _chat(db_session, "race")
    target = _message(db_session, chat, external_id="in-1000", hour=10, text="Can you increase CPA?")
    db_session.commit()
    later = _message(db_session, chat, external_id="in-1001", hour=10, minute=1, text="bump")
    db_session.commit()

    # Target was chosen as `target`; a newer message already exists when analysis is stored.
    analysis = _analyze(db_session, target.id)
    payload = api_client.get(f"/chats/{chat.id}/analysis").json()
    assert payload["id"] == analysis.id
    assert payload["message_id"] == target.id
    assert later.id > target.id
    assert payload["is_stale"] is True
    assert payload["newer_messages_count"] == 1
    assert payload["latest_message_id"] == later.id


def test_new_message_does_not_delete_analysis_or_call_ai(
    db_session: Session, monkeypatch
) -> None:
    chat = _chat(db_session, "no-ai")
    target = _message(db_session, chat, external_id="in-1000", hour=10, text="Can you increase CPA?")
    analysis = _analyze(db_session, target.id)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("new messages must not call AI")

    monkeypatch.setattr("app.ai.factory.get_ai_provider", boom)
    _message(db_session, chat, external_id="in-1005", hour=10, minute=5, text="ok thanks")
    db_session.commit()

    assert db_session.get(AIAnalysis, analysis.id) is not None
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 1
    assert latest_chat_analysis(db_session, chat.id).id == analysis.id
    assert analysis_is_stale(db_session, analysis) is True
