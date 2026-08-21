"""PHASE 7.1 smart reply: UNKNOWN may need a reply, an answered message may not."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockAIProvider
from app.ai.provider import AIProvider
from app.database.upgrade import apply_schema_upgrades
from app.enums import (
    AnalysisCategory,
    ChatType,
    DirectionSource,
    MessageDirection,
    Platform,
    Priority,
)
from app.models import Chat, Message
from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult, ImportantEntities
from app.schemas.digest import DigestAIOutput
from app.services.analysis import AIAnalysisService
from app.services.inbox import analysis_target_message, has_outgoing_after_message
from app.services.message_direction import set_message_direction


class StubProvider(AIProvider):
    """Deterministic provider so tests control what the model claims."""

    name = "stub"
    model = "stub-v1"
    resolved_model = "stub-v1"

    def __init__(self, result: AIAnalysisResult) -> None:
        self.result = result
        self.contexts: list[AIAnalysisContext] = []

    async def analyze_message(self, context: AIAnalysisContext) -> AIAnalysisResult:
        self.contexts.append(context)
        return self.result

    async def summarize_digest(self, payload: dict) -> DigestAIOutput:
        raise AssertionError("digest must not be called from conversation analysis")

    async def answer_digest_qa(self, payload: dict):
        raise AssertionError("digest Q&A must not be called from conversation analysis")


def _result(*, needs_reply: bool, draft_reply: str | None) -> AIAnalysisResult:
    return AIAnalysisResult(
        summary="Партнёр спрашивает ставку CPA.",
        request="Сообщить текущий CPA.",
        conversation_explanation_ru="Партнёр просит назвать ставку CPA по своему трафику.",
        next_action_ru="Ответить партнёру.",
        category=AnalysisCategory.AFFILIATE,
        priority=Priority.NORMAL,
        needs_reply=needs_reply,
        needs_igor=False,
        reason="Прямой вопрос про условия.",
        draft_reply=draft_reply,
        important_entities=ImportantEntities(),
    )


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 18, hour, minute, tzinfo=timezone.utc)


def _chat(session: Session, external_id: str) -> Chat:
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
    text_body: str,
    at: datetime,
    direction: MessageDirection,
) -> Message:
    source = {
        MessageDirection.UNKNOWN: DirectionSource.UNKNOWN,
        MessageDirection.INCOMING: DirectionSource.NATIVE,
        MessageDirection.OUTGOING: DirectionSource.NATIVE,
    }[direction]
    message = Message(
        chat_id=chat.id,
        external_id=external_id,
        sender_name="John" if direction != MessageDirection.OUTGOING else "Igor",
        text=text_body,
        timestamp=at,
        direction=direction,
        direction_source=source,
        is_outgoing=direction == MessageDirection.OUTGOING,
    )
    session.add(message)
    session.flush()
    return message


def test_scenario_a_unknown_question_gets_provisional_draft(db_session: Session) -> None:
    chat = _chat(db_session, "tx-a")
    target = _message(
        db_session,
        chat,
        external_id="a-1",
        text_body="Can you send me the CPA?",
        at=_ts(10),
        direction=MessageDirection.UNKNOWN,
    )
    db_session.commit()
    provider = StubProvider(_result(needs_reply=True, draft_reply="Sure, sending the CPA now."))
    service = AIAnalysisService(db_session, provider)

    analysis = asyncio.run(service.analyze_message(target.id))
    db_session.commit()

    assert analysis.needs_reply is True
    assert analysis.draft_reply == "Sure, sending the CPA now."
    assert analysis.direction_confirmation_required is True
    assert analysis.draft_is_provisional is True
    assert provider.contexts[0].already_answered is False


def test_scenario_b_unknown_with_outgoing_after_is_answered(db_session: Session) -> None:
    chat = _chat(db_session, "tx-b")
    target = _message(
        db_session,
        chat,
        external_id="b-1",
        text_body="Can you send me the CPA?",
        at=_ts(10),
        direction=MessageDirection.UNKNOWN,
    )
    _message(
        db_session,
        chat,
        external_id="b-2",
        text_body="Sure, CPA is $20.",
        at=_ts(10, 5),
        direction=MessageDirection.OUTGOING,
    )
    db_session.commit()
    provider = StubProvider(_result(needs_reply=True, draft_reply="Sure, CPA is $20."))
    service = AIAnalysisService(db_session, provider)

    assert analysis_target_message(db_session, chat.id) is not None
    analysis = asyncio.run(service.analyze_message(target.id))
    db_session.commit()

    assert analysis.needs_reply is False
    assert analysis.draft_reply is None
    assert analysis.draft_is_provisional is False
    assert provider.contexts[0].already_answered is True
    assert "уже отправлен" in analysis.reason
    assert analysis.next_action_ru == "Ничего делать не нужно — ответ уже отправлен."


def test_scenario_c_incoming_with_outgoing_answer(db_session: Session) -> None:
    chat = _chat(db_session, "tx-c")
    target = _message(
        db_session,
        chat,
        external_id="c-1",
        text_body="Can you send me the CPA?",
        at=_ts(10),
        direction=MessageDirection.INCOMING,
    )
    _message(
        db_session,
        chat,
        external_id="c-2",
        text_body="Sure, CPA is $20.",
        at=_ts(10, 5),
        direction=MessageDirection.OUTGOING,
    )
    db_session.commit()
    service = AIAnalysisService(
        db_session, StubProvider(_result(needs_reply=True, draft_reply="CPA is $20."))
    )

    analysis = asyncio.run(service.analyze_message(target.id))
    db_session.commit()

    assert analysis.needs_reply is False
    assert analysis.draft_reply is None
    assert analysis.direction_confirmation_required is False


def test_scenario_d_unknown_acknowledgement_needs_no_reply(db_session: Session) -> None:
    chat = _chat(db_session, "tx-d")
    target = _message(
        db_session,
        chat,
        external_id="d-1",
        text_body="ok thanks",
        at=_ts(10),
        direction=MessageDirection.UNKNOWN,
    )
    db_session.commit()
    service = AIAnalysisService(
        db_session, StubProvider(_result(needs_reply=False, draft_reply=None))
    )

    analysis = asyncio.run(service.analyze_message(target.id))
    db_session.commit()

    assert analysis.needs_reply is False
    assert analysis.draft_reply is None
    assert analysis.direction_confirmation_required is True
    assert analysis.draft_is_provisional is False


def test_scenario_e_manual_incoming_drops_provisional_flags(db_session: Session) -> None:
    chat = _chat(db_session, "tx-e")
    target = _message(
        db_session,
        chat,
        external_id="e-1",
        text_body="Can you send me the CPA?",
        at=_ts(10),
        direction=MessageDirection.UNKNOWN,
    )
    db_session.commit()
    service = AIAnalysisService(
        db_session, StubProvider(_result(needs_reply=True, draft_reply="Sure, CPA is $20."))
    )
    provisional = asyncio.run(service.analyze_message(target.id))
    db_session.commit()
    assert provisional.draft_is_provisional is True

    set_message_direction(db_session, target.id, MessageDirection.INCOMING)
    db_session.commit()
    confirmed = asyncio.run(service.analyze_message(target.id))
    db_session.commit()

    assert confirmed.needs_reply is True
    assert confirmed.draft_reply == "Sure, CPA is $20."
    assert confirmed.direction_confirmation_required is False
    assert confirmed.draft_is_provisional is False


def test_has_outgoing_after_message_tie_breaks_on_id(db_session: Session) -> None:
    chat = _chat(db_session, "tx-tie")
    target = _message(
        db_session,
        chat,
        external_id="t-1",
        text_body="им нужно нам показать",
        at=_ts(10, 9),
        direction=MessageDirection.UNKNOWN,
    )
    db_session.commit()
    assert has_outgoing_after_message(db_session, target) is False

    same_minute_reply = _message(
        db_session,
        chat,
        external_id="t-2",
        text_body="Ok",
        at=_ts(10, 9),
        direction=MessageDirection.OUTGOING,
    )
    db_session.commit()
    assert same_minute_reply.id > target.id
    assert has_outgoing_after_message(db_session, target) is True
    assert has_outgoing_after_message(db_session, same_minute_reply) is False


def test_outgoing_before_target_does_not_count(db_session: Session) -> None:
    chat = _chat(db_session, "tx-before")
    _message(
        db_session,
        chat,
        external_id="p-1",
        text_body="Any update?",
        at=_ts(9),
        direction=MessageDirection.OUTGOING,
    )
    target = _message(
        db_session,
        chat,
        external_id="p-2",
        text_body="Can you send me the CPA?",
        at=_ts(10),
        direction=MessageDirection.UNKNOWN,
    )
    db_session.commit()

    assert has_outgoing_after_message(db_session, target) is False


def test_mock_provider_fills_russian_explanation_and_next_action(db_session: Session) -> None:
    chat = _chat(db_session, "tx-explain")
    target = _message(
        db_session,
        chat,
        external_id="x-1",
        text_body="Can we increase CPA for Indonesia PWA traffic?",
        at=_ts(10),
        direction=MessageDirection.UNKNOWN,
    )
    db_session.commit()
    service = AIAnalysisService(db_session, MockAIProvider())

    analysis = asyncio.run(service.analyze_message(target.id))
    db_session.commit()

    assert analysis.conversation_explanation_ru
    assert "CPA —" in analysis.conversation_explanation_ru
    assert analysis.next_action_ru


def test_analysis_api_exposes_explanation_and_flags(api_client, db_session: Session) -> None:
    chat = _chat(db_session, "tx-api")
    _message(
        db_session,
        chat,
        external_id="api-1",
        text_body="Can we increase CPA for Indonesia PWA traffic?",
        at=_ts(10),
        direction=MessageDirection.UNKNOWN,
    )
    db_session.commit()

    response = api_client.post(f"/chats/{chat.id}/analyze")
    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_explanation_ru"]
    assert payload["next_action_ru"]
    assert payload["direction_confirmation_required"] is True
    assert payload["draft_is_provisional"] is True

    stored = api_client.get(f"/chats/{chat.id}/analysis").json()
    assert stored["conversation_explanation_ru"] == payload["conversation_explanation_ru"]


def test_legacy_ai_analyses_table_gains_explanation_columns(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ai_analyses (
                    id INTEGER PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    request TEXT NOT NULL,
                    category VARCHAR(16) NOT NULL,
                    priority VARCHAR(16) NOT NULL,
                    needs_reply BOOLEAN NOT NULL,
                    needs_igor BOOLEAN NOT NULL,
                    reason TEXT NOT NULL,
                    draft_reply TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO ai_analyses (message_id, summary, request, category, priority,"
                " needs_reply, needs_igor, reason)"
                " VALUES (1, 's', 'r', 'other', 'normal', 0, 0, 'legacy row')"
            )
        )

    apply_schema_upgrades(engine)
    apply_schema_upgrades(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("ai_analyses")}
    assert {"conversation_explanation_ru", "next_action_ru"} <= columns
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT reason, conversation_explanation_ru FROM ai_analyses")
        ).one()
    assert row[0] == "legacy row"
    assert row[1] is None
    engine.dispose()


def test_analysis_service_has_no_send_path() -> None:
    source = Path("app/services/analysis.py").read_text(encoding="utf-8")
    for forbidden in ("send_message", ".send(", "send_text"):
        assert forbidden not in source
