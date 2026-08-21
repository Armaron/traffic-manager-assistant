import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockAIProvider
from app.ai.openrouter_provider import OpenRouterProvider
from app.enums import (
    AnalysisCategory,
    ChatType,
    ConversationStatus,
    DirectionSource,
    MessageDirection,
    Platform,
    Priority,
)
from app.models import AIAnalysis, Chat, Message
from app.schemas.digest import DigestQAHistoryTurn, DigestQAModelOutput
from app.services.digest import build_digest
from app.services.digest_qa import (
    QA_HISTORY_TURNS,
    cap_history,
    retrieve_qa_context,
    tokenize,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def _chat(
    session: Session,
    *,
    external_id: str,
    name: str,
    platform: Platform = Platform.SLACK,
) -> Chat:
    chat = Chat(
        platform=platform,
        external_id=external_id,
        name=name,
        chat_type=ChatType.DIRECT,
        status=ConversationStatus.NEW,
    )
    session.add(chat)
    session.flush()
    return chat


def _msg(
    session: Session,
    chat: Chat,
    *,
    external_id: str,
    text: str,
    hours: float = 1,
    direction: MessageDirection = MessageDirection.INCOMING,
    sender: str = "Partner",
    timestamp: datetime | None = None,
) -> Message:
    message = Message(
        chat_id=chat.id,
        external_id=external_id,
        sender_name=sender,
        text=text,
        timestamp=timestamp or (NOW - timedelta(hours=hours)),
        direction=direction,
        direction_source=DirectionSource.UNKNOWN if direction == MessageDirection.UNKNOWN else DirectionSource.NATIVE,
        created_at=NOW,
    )
    session.add(message)
    session.flush()
    return message


def _analysis(session: Session, message: Message, *, explanation: str) -> None:
    row = AIAnalysis(
        message_id=message.id,
        summary="stale-or-fresh",
        request="request",
        category=AnalysisCategory.OTHER,
        priority=Priority.NORMAL,
        needs_reply=True,
        needs_igor=False,
        reason="reason",
        conversation_explanation_ru=explanation,
        next_action_ru="Ответить",
        provider="mock",
        model="mock-v1",
    )
    session.add(row)
    session.flush()


def _retrieve(session: Session, question: str, history=None):
    digest = build_digest(session, period="24h", now=NOW)
    return retrieve_qa_context(session, question=question, digest=digest, history=history or [])


def test_named_chat_ranks_high(db_session: Session) -> None:
    adam = _chat(db_session, external_id="adam", name="Adam Scott")
    other = _chat(db_session, external_id="other", name="Random Partner")
    _msg(db_session, adam, external_id="a1", text="Can we start Indonesia next week?")
    _msg(db_session, other, external_id="o1", text="Hello there, please send stats")
    retrieved = _retrieve(db_session, "Что было с Adam Scott?")
    names = [chat.item.chat_name for chat in retrieved.chats]
    assert names[0] == "Adam Scott"
    assert len(retrieved.chats) <= 6


def test_cpa_query_finds_cpa_messages(db_session: Session) -> None:
    chat = _chat(db_session, external_id="cpa", name="Jacqueline")
    hit = _msg(db_session, chat, external_id="c1", text="Can we do CPA $20 for Indonesia?")
    _msg(db_session, chat, external_id="c2", text="ok", hours=0.5, direction=MessageDirection.OUTGOING, sender="Igor")
    retrieved = _retrieve(db_session, "Что было по CPA?")
    texts = [item["text"] for item in retrieved.sources]
    assert any("CPA $20" in text for text in texts)
    assert any(item["alias"] for item in retrieved.sources)


def test_igor_actions_prioritize_meaningful_outgoing_not_ack(db_session: Session) -> None:
    useful = _chat(db_session, external_id="u", name="Useful")
    ack = _chat(db_session, external_id="a", name="Ack Only")
    _msg(db_session, useful, external_id="in", text="Need the report", hours=2)
    _msg(
        db_session,
        useful,
        external_id="out",
        text="I sent the report with 120 FTD.",
        hours=1,
        direction=MessageDirection.OUTGOING,
        sender="Igor",
    )
    _msg(db_session, ack, external_id="in2", text="Thanks for yesterday", hours=2)
    _msg(db_session, ack, external_id="out2", text="ok", hours=1, direction=MessageDirection.OUTGOING, sender="Igor")
    retrieved = _retrieve(db_session, "Что сегодня сделал Игорь?")
    assert retrieved.chats[0].item.chat_name == "Useful"
    blob = json.dumps(retrieved.payload, ensure_ascii=False)
    assert "I sent the report with 120 FTD." in blob


def test_needs_reply_and_waiting_intents(db_session: Session) -> None:
    waiting_us = _chat(db_session, external_id="nr", name="Needs Reply")
    waiting_them = _chat(db_session, external_id="wt", name="Waiting Them")
    _msg(db_session, waiting_us, external_id="out", text="I will send stats later", hours=3, direction=MessageDirection.OUTGOING, sender="Igor")
    _msg(db_session, waiting_us, external_id="in", text="Any update on the stats?", hours=1)
    _msg(db_session, waiting_them, external_id="in2", text="Please confirm GEO", hours=3)
    _msg(db_session, waiting_them, external_id="out2", text="I sent the GEO list, waiting for your confirmation.", hours=1, direction=MessageDirection.OUTGOING, sender="Igor")
    reply_ctx = _retrieve(db_session, "Кому надо ответить?")
    wait_ctx = _retrieve(db_session, "Что ждём от других?")
    assert reply_ctx.chats[0].item.chat_name == "Needs Reply"
    assert wait_ctx.chats[0].item.chat_name == "Waiting Them"


def test_stale_ai_not_authoritative(db_session: Session) -> None:
    chat = _chat(db_session, external_id="stale", name="Stale AI")
    analyzed = _msg(db_session, chat, external_id="in", text="Simple hello from partner", hours=3)
    _analysis(db_session, analyzed, explanation="Секретный выдуманный сюжет про unicorn deal")
    _msg(db_session, chat, external_id="later", text="later ping", hours=1)
    retrieved = _retrieve(db_session, "unicorn deal")
    encoded = json.dumps({key: retrieved.payload[key] for key in ("sources", "chats")}, ensure_ascii=False)
    assert "unicorn deal" not in encoded.lower()


def test_period_and_pre_period_context(db_session: Session) -> None:
    chat = _chat(db_session, external_id="per", name="Period Chat")
    old = _msg(db_session, chat, external_id="old", text="Old pre-period context about Nigeria", hours=48)
    new = _msg(db_session, chat, external_id="new", text="New Indonesia lead today", hours=2)
    retrieved = _retrieve(db_session, "Что было по Indonesia?")
    by_id = {item["text"]: item for item in retrieved.sources}
    assert any(item["inside_period"] is False for item in retrieved.sources if "Nigeria" in item["text"])
    indonesia = next(item for item in retrieved.sources if "Indonesia" in item["text"])
    assert indonesia["inside_period"] is True
    digest = build_digest(db_session, period="24h", now=NOW)
    assert digest.counts.messages == 1
    assert old.id != new.id


def test_caps_enforced(db_session: Session) -> None:
    named = _chat(db_session, external_id="focus", name="Named Target")
    _msg(db_session, named, external_id="n1", text="Named Target asked for invoice 4412")
    for index in range(30):
        chat = _chat(db_session, external_id=f"x{index}", name=f"Filler {index}")
        _msg(db_session, chat, external_id=f"m{index}", text=f"generic update {index} about weather")
    retrieved = _retrieve(db_session, "Что было с Named Target?")
    assert len(retrieved.chats) <= 6
    assert len(retrieved.sources) <= 70
    encoded = json.dumps(retrieved.payload, ensure_ascii=False)
    assert len(encoded) <= 60_000


def test_mock_factuality_and_numbers(db_session: Session) -> None:
    import asyncio

    from app.services.digest_qa import answer_digest_question

    chat = _chat(db_session, external_id="fact", name="Partner")
    _msg(db_session, chat, external_id="f1", text="I will send the report tomorrow.", hours=3, direction=MessageDirection.OUTGOING, sender="Igor")
    _msg(db_session, chat, external_id="f2", text="I sent the GEO sheet.", hours=2, direction=MessageDirection.OUTGOING, sender="Igor")
    _msg(db_session, chat, external_id="f3", text="I'll check with Nick.", hours=1.5, direction=MessageDirection.OUTGOING, sender="Igor")
    _msg(db_session, chat, external_id="f4", text="Can we do CPA $19.19?", hours=1)
    _msg(db_session, chat, external_id="f5", text="Maybe later", hours=0.5, direction=MessageDirection.UNKNOWN, sender="Someone")
    future = asyncio.run(answer_digest_question(db_session, question="Что сегодня сделал Игорь?", period="24h", now=NOW, provider=MockAIProvider()))
    assert "отправит" in future.answer_ru or "сообщил, что отправит" in future.answer_ru
    assert "уточнит" in future.answer_ru or "проверит" in future.answer_ru
    cpa = asyncio.run(answer_digest_question(db_session, question="Что было по CPA?", period="24h", now=NOW, provider=MockAIProvider()))
    assert "CPA $19.19" in cpa.answer_ru
    assert "нет подтверждения" in cpa.answer_ru.lower()
    unknown = asyncio.run(
        answer_digest_question(db_session, question="Что было с Someone later?", period="24h", now=NOW, provider=MockAIProvider())
    )
    assert "действие Игоря" not in unknown.answer_ru or "не действие Игоря" in unknown.answer_ru


def test_missing_evidence_uncertainty(db_session: Session) -> None:
    import asyncio

    from app.services.digest_qa import answer_digest_question

    chat = _chat(db_session, external_id="empty", name="Quiet")
    _msg(db_session, chat, external_id="q", text="hello")
    result = asyncio.run(
        answer_digest_question(db_session, question="Какой был закрытый контракт с NASA?", period="24h", now=NOW, provider=MockAIProvider())
    )
    assert result.uncertainty_ru or "не нашёл" in result.answer_ru.lower() or "не нашел" in result.answer_ru.lower()


def test_source_refs_map_and_unknown_alias_dropped(db_session: Session) -> None:
    import asyncio

    from app.services.digest_qa import answer_digest_question

    class Fake(MockAIProvider):
        async def answer_digest_qa(self, payload: dict) -> DigestQAModelOutput:
            aliases = [item["alias"] for item in payload["sources"][:1]]
            return DigestQAModelOutput(
                answer_ru="Ок",
                source_refs=[*aliases, "S999", "made-up"],
                uncertainty_ru=None,
                suggested_questions_ru=[],
            )

    chat = _chat(db_session, external_id="src", name="Source Chat")
    message = _msg(db_session, chat, external_id="s1", text="Need invoice copy")
    result = asyncio.run(answer_digest_question(db_session, question="Что с invoice?", period="24h", now=NOW, provider=Fake()))
    assert result.sources
    assert result.sources[0].chat_id == chat.id
    assert result.sources[0].message_id == message.id
    assert all(item.message_id != 0 for item in result.sources)
    assert len(result.sources) == 1


def test_history_capped_and_follow_up_supplied(api_client: TestClient, db_session: Session, monkeypatch) -> None:
    captured: list[dict] = []

    class Capture(MockAIProvider):
        async def answer_digest_qa(self, payload: dict) -> DigestQAModelOutput:
            captured.append(payload)
            return await super().answer_digest_qa(payload)

    monkeypatch.setattr("app.services.digest_qa.get_ai_provider", lambda: Capture())
    chat = _chat(db_session, external_id="hist", name="History")
    _msg(db_session, chat, external_id="h1", text="Can we do CPA $20?")
    db_session.commit()
    history = [{"role": "user" if index % 2 == 0 else "assistant", "content": f"turn {index} " + ("x" * 200)} for index in range(20)]
    api_client.post(
        "/digest/qa",
        json={
            "period": "24h",
            "question": "А кто из них уже получил ответ?",
            "history": history,
        },
    )
    assert captured
    assert len(captured[0]["history"]) <= QA_HISTORY_TURNS
    assert all(item.get("authoritative") is False for item in captured[0]["history"] if item["role"] == "assistant")
    turns = cap_history([DigestQAHistoryTurn(role="user", content="a" * 5000) for _ in range(20)])
    assert len(turns) <= QA_HISTORY_TURNS


def test_one_openrouter_call_uses_selected_model(monkeypatch) -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        captured.append(body)
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_ru": "Нет данных",
                                    "source_refs": [],
                                    "uncertainty_ru": "В выбранном периоде недостаточно данных.",
                                    "suggested_questions_ru": [],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenRouterProvider(
        api_key="test-key",
        model="anthropic/claude-sonnet-4.6",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    import asyncio

    asyncio.run(provider.answer_digest_qa({"question": "test", "sources": []}))
    assert len(captured) == 1
    assert captured[0]["model"] == "anthropic/claude-sonnet-4.6"
    encoded = json.dumps(captured[0])
    assert "raw_data" not in encoded
    assert "stringsession" not in encoded.lower()
    assert "api_hash" not in encoded


def test_model_failure_is_not_rerouted(api_client: TestClient, db_session: Session, monkeypatch) -> None:
    from app.ai.errors import AIModelUnavailableError

    class Boom(MockAIProvider):
        async def answer_digest_qa(self, payload: dict):
            raise AIModelUnavailableError("OpenRouter model unavailable")

    monkeypatch.setattr("app.services.digest_qa.get_ai_provider", lambda: Boom())
    chat = _chat(db_session, external_id="boom", name="Boom")
    _msg(db_session, chat, external_id="b", text="hello")
    db_session.commit()
    response = api_client.post(
        "/digest/qa",
        json={"period": "24h", "model": "anthropic/claude-opus-5", "question": "Что сделал Игорь?"},
    )
    assert response.status_code == 502
    assert "gemini" not in response.text.lower()


def test_qa_payload_has_no_secrets_or_binaries(db_session: Session) -> None:
    chat = _chat(db_session, external_id="sec", name="Secure")
    _msg(db_session, chat, external_id="s", text="Please send invoice")
    retrieved = _retrieve(db_session, "invoice")
    encoded = json.dumps(retrieved.payload).lower()
    for needle in ("raw_data", "api_hash", "stringsession", "slack_user_token", "browser_local", "phone"):
        assert needle not in encoded
    assert "sources" in retrieved.payload


def test_get_digest_does_not_call_qa(api_client: TestClient, db_session: Session, monkeypatch) -> None:
    provider = MockAIProvider()
    monkeypatch.setattr("app.services.digest_qa.get_ai_provider", lambda: provider)
    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: provider)
    chat = _chat(db_session, external_id="open", name="Open")
    _msg(db_session, chat, external_id="o", text="hello")
    db_session.commit()
    api_client.get("/digest", params={"period": "24h"})
    api_client.get("/ai/models")
    assert provider.qa_calls == 0
    assert provider.digest_calls == 0


def test_tokenize_keeps_cpa_and_names() -> None:
    tokens = tokenize("Что было по CPA с Adam Scott")
    assert "cpa" in tokens
    assert "adam" in tokens
    assert "scott" in tokens
