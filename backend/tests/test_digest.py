from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.ai.errors import AIRateLimitError, AIUnavailableError
from app.ai.mock_provider import MockAIProvider
from app.enums import (
    AnalysisCategory,
    ChatType,
    ConversationStatus,
    DirectionSource,
    MessageDirection,
    Platform,
    Priority,
    TranslationStatus,
)
from app.models import AIAnalysis, Chat, Message, MessageTranslation
from app.schemas.digest import DigestAIOutput
from app.services.digest import build_digest, high_stakes_in_text, resolve_period
from app.services.digest_ai import AI_MAX_CHARS, AI_MAX_ITEMS, build_ai_payload, generate_ai_digest, select_ai_candidates

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def _ts(*, hours=0, minutes=0, seconds=0) -> datetime:
    return NOW - timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _chat(session: Session, *, platform=Platform.TYPEX, external_id: str, name: str, status=ConversationStatus.NEW) -> Chat:
    chat = Chat(platform=platform, external_id=external_id, name=name, chat_type=ChatType.DIRECT, status=status)
    session.add(chat)
    session.flush()
    return chat


def _msg(
    session: Session,
    chat: Chat,
    *,
    external_id: str,
    timestamp: datetime,
    text: str = "hello",
    direction: MessageDirection = MessageDirection.INCOMING,
    source: DirectionSource | None = None,
    created_at: datetime | None = None,
) -> Message:
    message = Message(
        chat_id=chat.id,
        external_id=external_id,
        sender_name="Partner",
        text=text,
        timestamp=timestamp,
        direction=direction,
        direction_source=source
        or (DirectionSource.UNKNOWN if direction == MessageDirection.UNKNOWN else DirectionSource.NATIVE),
        created_at=created_at or NOW,
    )
    session.add(message)
    session.flush()
    return message


def _analysis(
    session: Session,
    message: Message,
    *,
    needs_reply=False,
    needs_igor=False,
    priority=Priority.NORMAL,
    explanation="Свежий разбор",
    next_action="Ответить",
) -> AIAnalysis:
    row = AIAnalysis(
        message_id=message.id,
        summary="summary",
        request="request",
        category=AnalysisCategory.OTHER,
        priority=priority,
        needs_reply=needs_reply,
        needs_igor=needs_igor,
        reason="reason",
        conversation_explanation_ru=explanation,
        next_action_ru=next_action,
        provider="mock",
        model="mock-v1",
    )
    session.add(row)
    session.flush()
    return row


def _digest(session: Session, **kwargs):
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("period", "24h")
    return build_digest(session, **kwargs)


def test_period_uses_message_timestamp_not_created_at(db_session: Session) -> None:
    chat = _chat(db_session, external_id="t1", name="A")
    inside = _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), created_at=_ts(hours=48))
    _msg(db_session, chat, external_id="old", timestamp=_ts(hours=48), created_at=_ts(minutes=1), text="old")
    digest = _digest(db_session)
    assert digest.counts.messages == 1
    assert digest.items[0].target_message_id == inside.id


def test_boundary_inclusive_and_exclusive(db_session: Session) -> None:
    chat = _chat(db_session, external_id="bound", name="B")
    window = resolve_period(period="24h", now=NOW)
    _msg(db_session, chat, external_id="in", timestamp=window.start, text="inside")
    _msg(db_session, chat, external_id="out", timestamp=window.start - timedelta(seconds=1), text="outside")
    digest = _digest(db_session)
    assert digest.counts.messages == 1
    assert "inside" in digest.items[0].snippet
    assert "outside" not in digest.items[0].snippet


def test_distinct_active_chats_and_one_item_per_chat(db_session: Session) -> None:
    first = _chat(db_session, external_id="c1", name="One")
    second = _chat(db_session, external_id="c2", name="Two")
    _msg(db_session, first, external_id="a", timestamp=_ts(hours=1))
    _msg(db_session, first, external_id="b", timestamp=_ts(minutes=30), text="second")
    _msg(db_session, second, external_id="c", timestamp=_ts(hours=2))
    digest = _digest(db_session)
    assert digest.counts.active_chats == 2
    assert len(digest.items) == 2
    one = next(item for item in digest.items if item.chat_id == first.id)
    assert one.source_message_count == 2


def test_incoming_after_outgoing_needs_reply(db_session: Session) -> None:
    chat = _chat(db_session, external_id="nr", name="Need")
    _msg(db_session, chat, external_id="out", timestamp=_ts(hours=3), direction=MessageDirection.OUTGOING, text="sent")
    incoming = _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="Can you send the stats?")
    item = _digest(db_session).items[0]
    assert item.needs_reply is True
    assert item.already_answered is False
    assert item.target_message_id == incoming.id
    assert item.primary_state == "needs_reply"


def test_outgoing_after_incoming_already_answered(db_session: Session) -> None:
    chat = _chat(db_session, external_id="aa", name="Answered")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=2), text="Can you send the stats?")
    _msg(db_session, chat, external_id="out", timestamp=_ts(hours=1), direction=MessageDirection.OUTGOING, text="Sure, one moment.")
    item = _digest(db_session).items[0]
    assert item.already_answered is True
    assert item.needs_reply is False
    assert item.waiting is True


def test_latest_outgoing_waiting(db_session: Session) -> None:
    chat = _chat(db_session, external_id="w", name="Wait")
    _msg(db_session, chat, external_id="out", timestamp=_ts(hours=1), direction=MessageDirection.OUTGOING, text="ping")
    item = _digest(db_session).items[0]
    assert item.waiting is True
    assert item.primary_state == "waiting"


def test_manual_needs_reply_and_igor(db_session: Session) -> None:
    reply = _chat(db_session, external_id="mr", name="Manual reply", status=ConversationStatus.NEEDS_REPLY)
    igor = _chat(db_session, external_id="mi", name="Manual igor", status=ConversationStatus.NEEDS_IGOR)
    _msg(db_session, reply, external_id="1", timestamp=_ts(hours=1), direction=MessageDirection.OUTGOING, text="we sent")
    _msg(db_session, igor, external_id="2", timestamp=_ts(hours=1), text="hi")
    digest = _digest(db_session)
    by_name = {item.chat_name: item for item in digest.items}
    assert by_name["Manual reply"].needs_reply is True
    assert by_name["Manual igor"].needs_igor is True


def test_resolved_not_needs_reply_unless_new_incoming(db_session: Session) -> None:
    closed = _chat(db_session, external_id="res", name="Closed", status=ConversationStatus.RESOLVED)
    _msg(db_session, closed, external_id="out", timestamp=_ts(hours=1), direction=MessageDirection.OUTGOING, text="done")
    item = _digest(db_session).items[0]
    assert item.resolved is True
    assert item.needs_reply is False

    fresh = _chat(db_session, external_id="res2", name="Reopened", status=ConversationStatus.RESOLVED)
    _msg(db_session, fresh, external_id="old", timestamp=_ts(hours=3), direction=MessageDirection.OUTGOING, text="done")
    _msg(db_session, fresh, external_id="new", timestamp=_ts(hours=1), text="new question")
    reopened = next(item for item in _digest(db_session).items if item.chat_name == "Reopened")
    assert reopened.resolved is False
    assert reopened.needs_reply is True


def test_fresh_ai_flags_used_stale_ignored(db_session: Session) -> None:
    fresh_chat = _chat(db_session, external_id="fresh", name="Fresh")
    target = _msg(db_session, fresh_chat, external_id="in", timestamp=_ts(hours=1), text="please reply")
    _analysis(db_session, target, needs_reply=True, needs_igor=True, priority=Priority.HIGH)

    stale_chat = _chat(db_session, external_id="stale", name="Stale")
    old = _msg(db_session, stale_chat, external_id="old", timestamp=_ts(hours=3), text="old")
    _analysis(db_session, old, needs_reply=True, needs_igor=True, priority=Priority.URGENT)
    _msg(db_session, stale_chat, external_id="later", timestamp=_ts(hours=1), direction=MessageDirection.OUTGOING, text="answered")

    digest = _digest(db_session)
    by_name = {item.chat_name: item for item in digest.items}
    assert by_name["Fresh"].needs_reply is True
    assert by_name["Fresh"].needs_igor is True
    assert by_name["Fresh"].urgent is True
    assert by_name["Fresh"].analysis_fresh is True
    assert by_name["Stale"].analysis_fresh is False
    assert by_name["Stale"].needs_igor is False
    assert by_name["Stale"].urgent is False
    assert by_name["Stale"].already_answered is True


def test_high_stakes_review_not_decision(db_session: Session) -> None:
    chat = _chat(db_session, external_id="cpa", name="Jacqueline")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="Can you confirm CPA $20 for Indonesia?")
    item = _digest(db_session).items[0]
    assert item.high_stakes is True
    assert item.needs_igor is True
    assert "согласиться" not in item.next_action_ru.lower()
    assert "принять cpa" not in item.next_action_ru.lower()
    assert "ручная проверка" in item.next_action_ru
    assert high_stakes_in_text("RevShare 40%") is True


def test_sorting_urgent_first_then_latest(db_session: Session) -> None:
    older_urgent = _chat(db_session, external_id="u1", name="Older urgent")
    newer_reply = _chat(db_session, external_id="r1", name="Newer reply")
    u = _msg(db_session, older_urgent, external_id="u", timestamp=_ts(hours=5), text="campaign stopped today")
    _analysis(db_session, u, needs_reply=True, priority=Priority.URGENT)
    _msg(db_session, newer_reply, external_id="r", timestamp=_ts(minutes=10), text="stats please")
    names = [item.chat_name for item in _digest(db_session).items]
    assert names[0] == "Older urgent"
    assert names[1] == "Newer reply"


def test_custom_period_validation(api_client: TestClient) -> None:
    bad = api_client.get("/digest", params={"from": "2026-08-01T00:00:00Z", "to": "2026-07-01T00:00:00Z"})
    assert bad.status_code == 400
    long = api_client.get("/digest", params={"from": "2026-01-01T00:00:00Z", "to": "2026-03-15T00:00:00Z"})
    assert long.status_code == 400
    assert long.json()["detail"]["code"] == "period_too_long"


def test_hour_presets(api_client: TestClient) -> None:
    for key, hours in (("1h", 1), ("3h", 3), ("12h", 12)):
        window = resolve_period(period=key, now=NOW)
        assert window.label == key
        assert window.end == NOW
        assert window.start == NOW - timedelta(hours=hours)
        assert api_client.get("/digest", params={"period": key}).status_code == 200
    unknown = api_client.get("/digest", params={"period": "2h"})
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "invalid_period"


def test_platforms_grouped_as_slack(db_session: Session) -> None:
    typex = _chat(db_session, platform=Platform.TYPEX, external_id="tx", name="TypeX chat")
    tg = _chat(db_session, platform=Platform.TELEGRAM, external_id="tg", name="TG chat")
    slack = _chat(db_session, platform=Platform.SLACK, external_id="sl", name="Slack API")
    browser = _chat(db_session, platform=Platform.SLACK, external_id="br", name="Slack Browser")
    note = _chat(db_session, platform=Platform.SLACK, external_id="nt", name="Slack Notify")
    _msg(db_session, typex, external_id="1", timestamp=_ts(hours=1))
    _msg(db_session, tg, external_id="2", timestamp=_ts(hours=1))
    _msg(db_session, slack, external_id="3", timestamp=_ts(hours=1))
    _msg(db_session, browser, external_id="4", timestamp=_ts(hours=1), source=DirectionSource.UNKNOWN)
    _msg(db_session, note, external_id="5", timestamp=_ts(hours=1), source=DirectionSource.NOTIFICATION)
    digest = _digest(db_session)
    platforms = {item.chat_name: item.platform.value for item in digest.items}
    assert platforms["TypeX chat"] == "typex"
    assert platforms["TG chat"] == "telegram"
    assert platforms["Slack API"] == "slack"
    assert platforms["Slack Browser"] == "slack"
    assert platforms["Slack Notify"] == "slack"
    slack_only = _digest(db_session, platform=Platform.SLACK)
    assert {item.chat_name for item in slack_only.items} == {"Slack API", "Slack Browser", "Slack Notify"}


def test_translation_does_not_change_selection_or_hash(db_session: Session) -> None:
    chat = _chat(db_session, external_id="tr", name="Translated")
    message = _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="Please send stats")
    first = _digest(db_session)
    db_session.add(
        MessageTranslation(
            message_id=message.id,
            target_language="ru",
            source_text_hash="abc",
            translated_text="Пожалуйста пришлите статистику",
            status=TranslationStatus.COMPLETED,
        )
    )
    db_session.flush()
    second = _digest(db_session)
    assert first.items[0].needs_reply == second.items[0].needs_reply
    assert first.source_hash == second.source_hash
    assert second.items[0].snippet_translated == "Пожалуйста пришлите статистику"
    assert "Please send stats" in first.items[0].snippet or "stats" in first.items[0].snippet.lower()


def test_get_digest_does_not_call_ai(monkeypatch, api_client: TestClient, db_session: Session) -> None:
    chat = _chat(db_session, external_id="ai0", name="No AI")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="hello")
    db_session.commit()
    provider = MockAIProvider()

    def boom(*_args, **_kwargs):
        raise AssertionError("GET digest must not call OpenRouter")

    monkeypatch.setattr("app.ai.openrouter_provider.OpenRouterProvider.analyze_message", boom)
    monkeypatch.setattr("app.ai.openrouter_provider.OpenRouterProvider.summarize_digest", boom)
    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: provider)
    response = api_client.get("/digest", params={"period": "24h"})
    assert response.status_code == 200
    assert provider.digest_calls == 0
    assert provider.analyze_calls == 0
    payload = response.json()
    assert "raw_data" not in str(payload)


def test_ai_digest_one_request_and_cache(monkeypatch, api_client: TestClient, db_session: Session) -> None:
    provider = MockAIProvider()
    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: provider)
    for index in range(30):
        chat = _chat(db_session, external_id=f"m{index}", name=f"Chat {index}")
        _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="Need a reply please")
    db_session.commit()
    first = api_client.post("/digest/ai", json={"period": "24h"})
    assert first.status_code == 200
    assert provider.digest_calls == 1
    body = first.json()
    assert body["cached"] is False
    assert "executive_summary_ru" in body["result"]
    assert "igor_actions" in body["result"]
    assert "interactions" in body["result"]
    second = api_client.post("/digest/ai", json={"period": "24h"})
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert provider.digest_calls == 1
    forced = api_client.post("/digest/ai", json={"period": "24h", "force": True})
    assert forced.status_code == 200
    assert provider.digest_calls == 2


def test_candidate_and_char_caps() -> None:
    from app.schemas.digest import DigestCounts, DigestItem, DigestPeriod, DigestResponse
    from app.enums import Platform as P

    items = [
        DigestItem(
            chat_id=index,
            platform=P.TYPEX,
            chat_name=f"Chat {index}",
            status="NEW",
            primary_state="needs_reply",
            snippet="x" * 2000,
            summary_ru="y" * 2000,
            latest_message_at=NOW,
            source_message_count=1,
        )
        for index in range(80)
    ]
    selected = select_ai_candidates(items)
    assert len(selected) == AI_MAX_ITEMS
    digest = DigestResponse(
        period=DigestPeriod(label="24h", start=NOW - timedelta(hours=24), end=NOW),
        counts=DigestCounts(messages=80, active_chats=80),
        items=items,
        source_hash="abc",
    )
    payload, truncated = build_ai_payload(digest, selected)
    encoded = __import__("json").dumps(payload)
    assert truncated is True or len(encoded) <= AI_MAX_CHARS
    assert len(encoded) <= AI_MAX_CHARS
    assert "raw_data" not in payload
    assert all("snippet" in chat for chat in payload["chats"])


def test_malformed_and_rate_limit_ai(monkeypatch, api_client: TestClient, db_session: Session) -> None:
    chat = _chat(db_session, external_id="bad", name="Bad")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="hello there")
    db_session.commit()

    class BadProvider(MockAIProvider):
        async def summarize_digest(self, payload: dict) -> DigestAIOutput:
            raise AIUnavailableError("AI provider unavailable")

    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: BadProvider())
    response = api_client.post("/digest/ai", json={"period": "24h"})
    assert response.status_code == 502

    class Limited(MockAIProvider):
        async def summarize_digest(self, payload: dict) -> DigestAIOutput:
            raise AIRateLimitError("AI rate limit reached")

    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: Limited())
    limited = api_client.post("/digest/ai", json={"period": "24h"})
    assert limited.status_code == 429

    class Malformed(MockAIProvider):
        async def summarize_digest(self, payload: dict):
            return {"title_ru": ["not", "text"], "executive_summary_ru": 1}

    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: Malformed())
    malformed = api_client.post("/digest/ai", json={"period": "24h"})
    assert malformed.status_code == 502


def test_new_message_changes_source_hash_keeps_cache(api_client: TestClient, db_session: Session, monkeypatch) -> None:
    provider = MockAIProvider()
    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: provider)
    chat = _chat(db_session, external_id="hash", name="Hash")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="first")
    db_session.commit()
    api_client.post("/digest/ai", json={"period": "24h"})
    before = api_client.get("/digest", params={"period": "24h"}).json()
    assert before["ai"]["available"] is True
    assert before["ai"]["stale"] is False
    _msg(db_session, chat, external_id="in2", timestamp=_ts(minutes=10), text="second")
    db_session.commit()
    after = api_client.get("/digest", params={"period": "24h"}).json()
    assert after["source_hash"] != before["source_hash"]
    assert after["ai"]["available"] is True
    assert after["ai"]["stale"] is True
    assert after["ai"]["result"] is not None


def test_digest_is_read_only_observational(db_session: Session) -> None:
    chat = _chat(db_session, external_id="ro", name="Read", status=ConversationStatus.NEW)
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="hello")
    _digest(db_session)
    db_session.refresh(chat)
    assert chat.status is ConversationStatus.NEW


def test_query_count_is_batched(db_session: Session) -> None:
    for index in range(8):
        chat = _chat(db_session, external_id=f"q{index}", name=f"Q{index}")
        _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="hello")
        _msg(db_session, chat, external_id="out", timestamp=_ts(minutes=30), direction=MessageDirection.OUTGOING, text="ok")
    queries: list[str] = []

    def before(_conn, _cursor, statement, _params, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", before)
    try:
        _digest(db_session)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", before)
    assert len(queries) < 20


def test_preset_source_hash_ignores_sliding_clock(db_session: Session) -> None:
    chat = _chat(db_session, external_id="clock", name="Clock")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="hello")
    first = _digest(db_session, now=NOW)
    second = _digest(db_session, now=NOW + timedelta(seconds=45))
    assert first.source_hash == second.source_hash


def test_platform_filter_scopes_message_counts(db_session: Session) -> None:
    typex = _chat(db_session, platform=Platform.TYPEX, external_id="tx", name="TX")
    slack = _chat(db_session, platform=Platform.SLACK, external_id="sl", name="SL")
    _msg(db_session, typex, external_id="1", timestamp=_ts(hours=1))
    _msg(db_session, slack, external_id="2", timestamp=_ts(hours=1))
    _msg(db_session, slack, external_id="3", timestamp=_ts(minutes=20), text="second")
    slack_only = _digest(db_session, platform=Platform.SLACK)
    assert slack_only.counts.messages == 2
    assert slack_only.counts.active_chats == 1


def test_ai_payload_uses_original_not_translation(monkeypatch, db_session: Session) -> None:
    from app.services.digest_ai import generate_ai_digest

    chat = _chat(db_session, external_id="orig", name="Original")
    message = _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="Please confirm CPA $20")
    db_session.add(
        MessageTranslation(
            message_id=message.id,
            target_language="ru",
            source_text_hash="abc",
            translated_text="Пожалуйста подтвердите CPA $20",
            status=TranslationStatus.COMPLETED,
        )
    )
    db_session.flush()
    captured: list[dict] = []

    class Capture(MockAIProvider):
        async def summarize_digest(self, payload: dict) -> DigestAIOutput:
            captured.append(payload)
            return await super().summarize_digest(payload)

    import asyncio

    asyncio.run(generate_ai_digest(db_session, period="24h", now=NOW, provider=Capture()))
    assert captured
    encoded = __import__("json").dumps(captured[0])
    assert "Please confirm CPA $20" in encoded or "CPA $20" in encoded
    assert "raw_data" not in encoded
    assert "stringsession" not in encoded.lower()
    assert "api_hash" not in encoded


def test_payload_rejects_forbidden_keys() -> None:
    from app.services.digest_ai import assert_payload_safe

    with pytest.raises(ValueError):
        assert_payload_safe({"chats": [{"raw_data": {"secret": 1}}]})


def test_get_digest_does_not_bump_inbox_generation(api_client: TestClient, db_session: Session) -> None:
    from app.services.sync_runtime import get_sync_runtime

    chat = _chat(db_session, external_id="gen", name="Gen")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="hello")
    db_session.commit()
    before = get_sync_runtime().inbox_generation
    assert api_client.get("/digest", params={"period": "24h"}).status_code == 200
    assert get_sync_runtime().inbox_generation == before


def test_openrouter_digest_uses_existing_retry(monkeypatch) -> None:
    import asyncio

    from app.ai.errors import AIUnavailableError
    from app.ai.openrouter_provider import OpenRouterProvider

    provider = OpenRouterProvider(api_key="test-key", model="test-model")
    calls: list[int] = []

    async def fake_retry(_client, _request):
        calls.append(1)
        raise AIUnavailableError("AI provider unavailable")

    monkeypatch.setattr(provider, "_post_with_retry", fake_retry)
    with pytest.raises(AIUnavailableError):
        asyncio.run(provider.summarize_digest({"chats": []}))
    assert calls == [1]


def _review(session: Session, provider=None):
    import asyncio

    return asyncio.run(generate_ai_digest(session, period="24h", now=NOW, provider=provider or MockAIProvider()))


def test_outgoing_message_is_igor_interaction(db_session: Session) -> None:
    chat = _chat(db_session, external_id="out1", name="Partner A")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=2), text="Need stats")
    _msg(
        db_session,
        chat,
        external_id="out",
        timestamp=_ts(hours=1),
        direction=MessageDirection.OUTGOING,
        text="I sent the stats",
    )
    digest = _digest(db_session)
    assert digest.items[0].igor_participated is True
    review = _review(db_session)
    assert any(item.person_or_chat_ru == "Partner A" for item in review.result.interactions)
    actions = " ".join(item.action_ru for item in review.result.igor_actions)
    assert "отправил" in actions.lower()
    assert "сообщил, что отправит" not in actions.lower()


def test_incoming_only_not_igor_interaction(db_session: Session) -> None:
    chat = _chat(db_session, external_id="inonly", name="Incoming Only")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="Can you send stats?")
    digest = _digest(db_session)
    assert digest.items[0].igor_participated is False
    review = _review(db_session)
    assert all(item.person_or_chat_ru != "Incoming Only" for item in review.result.interactions)
    assert all(item.person_or_chat_ru != "Incoming Only" for item in review.result.igor_actions)


def test_future_send_not_completed(db_session: Session) -> None:
    chat = _chat(db_session, external_id="will", name="Future")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=2), text="stats?")
    _msg(
        db_session,
        chat,
        external_id="out",
        timestamp=_ts(hours=1),
        direction=MessageDirection.OUTGOING,
        text="I will send the stats",
    )
    review = _review(db_session)
    blob = " ".join(item.action_ru for item in review.result.igor_actions).lower()
    assert "сообщил, что отправит" in blob
    assert "игорь отправил материалы" not in blob


def test_sent_may_be_completed(db_session: Session) -> None:
    from app.services.digest_context import describe_outgoing_action

    action, _ = describe_outgoing_action("I sent the stats")
    assert "отправил" in action.lower()
    assert "что отправит" not in action.lower()


def test_will_check_not_checked() -> None:
    from app.services.digest_context import describe_outgoing_action

    action, _ = describe_outgoing_action("I'll check with Nick")
    assert "уточнит" in action.lower() or "проверит" in action.lower()
    assert "уже проверил" not in action.lower()


def test_incoming_cpa_not_approved_deal(db_session: Session) -> None:
    chat = _chat(db_session, external_id="cpa2", name="CPA Partner")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="Can you do CPA $20?")
    review = _review(db_session)
    blob = json_blob(review.result)
    assert "can you do cpa $20" in blob or "cpa $20" in blob
    assert "согласован cpa" not in blob
    assert "нужно согласиться" not in blob
    assert "deal closed" not in blob


def test_unknown_direction_not_igor_action(db_session: Session) -> None:
    chat = _chat(db_session, external_id="unk", name="Unknown Dir")
    _msg(
        db_session,
        chat,
        external_id="u",
        timestamp=_ts(hours=1),
        text="I sent the stats",
        direction=MessageDirection.UNKNOWN,
        source=DirectionSource.UNKNOWN,
    )
    digest = _digest(db_session)
    assert digest.items[0].igor_participated is False
    review = _review(db_session)
    assert all(item.person_or_chat_ru != "Unknown Dir" for item in review.result.igor_actions)
    assert all(item.person_or_chat_ru != "Unknown Dir" for item in review.result.interactions)


def test_ack_outgoing_excluded_from_igor_actions(db_session: Session) -> None:
    chat = _chat(db_session, external_id="ack", name="Ack Chat")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=2), text="Please confirm")
    _msg(
        db_session,
        chat,
        external_id="out",
        timestamp=_ts(hours=1),
        direction=MessageDirection.OUTGOING,
        text="ok",
    )
    review = _review(db_session)
    assert review.result.igor_actions == [] or all("ok" not in item.action_ru.lower() for item in review.result.igor_actions)


def test_result_numbers_preserved_exactly(db_session: Session) -> None:
    chat = _chat(db_session, external_id="nums", name="Numbers")
    _msg(
        db_session,
        chat,
        external_id="in",
        timestamp=_ts(hours=1),
        text="12 affiliate candidates approached, 4 active negotiations, 1 deal closed, CPA $19.19, 3,000 FTD",
    )
    review = _review(db_session)
    facts = " ".join(item.fact_ru for item in review.result.results_and_numbers)
    assert "12 affiliate candidates approached" in facts
    assert "4 active negotiations" in facts
    assert "1 deal closed" in facts
    assert "CPA $19.19" in facts or "19.19" in facts
    assert "3,000 FTD" in facts
    assert "13 affiliate" not in facts
    assert "20.00" not in facts


def test_file_ui_garbage_normalized() -> None:
    from app.services.digest_context import normalize_digest_text

    cleaned = normalize_digest_text(
        "PDF LNKD_INVOICE_109301532181.pdfPDFDetails Download Preview",
        "LNKD_INVOICE_109301532181.pdf",
    )
    assert "PDFDetails" not in cleaned
    assert "Download" not in cleaned
    assert "LNKD_INVOICE_109301532181.pdf" in cleaned
    assert cleaned.startswith("[File]")


def test_old_cache_schema_ignored(api_client: TestClient, db_session: Session) -> None:
    from app.models.digest import DigestAIResult
    from app.services.digest import filters_hash, resolve_period

    chat = _chat(db_session, external_id="oldc", name="Old Cache")
    _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="hello there")
    window = resolve_period(period="24h", now=NOW)
    db_session.add(
        DigestAIResult(
            period_label="24h",
            period_start=window.start,
            period_end=window.end,
            filters_hash=filters_hash(None),
            source_hash="anything",
            schema_version=1,
            result_json={"headline_ru": "old", "overview_ru": "legacy"},
            provider="mock",
            model="old",
        )
    )
    db_session.commit()
    payload = api_client.get("/digest", params={"period": "24h"}).json()
    assert payload["ai"]["available"] is False
    assert payload["ai"]["result"] is None


def test_ai_items_reference_supplied_ids(db_session: Session) -> None:
    from app.services.digest_ai import sanitize_ai_output
    from app.schemas.digest import DigestAIAction, DigestAIEntry, DigestAIOutput

    chat = _chat(db_session, external_id="ids", name="IDs")
    message = _msg(db_session, chat, external_id="in", timestamp=_ts(hours=1), text="Need a reply please")
    review = _review(db_session)
    allowed = {chat.id}
    for item in (
        review.result.main_events
        + review.result.needs_action
        + review.result.next_steps
        + list(review.result.igor_actions)
        + list(review.result.interactions)
    ):
        assert item.chat_id in allowed
        if item.message_id is not None:
            assert item.message_id == message.id

    dirty = DigestAIOutput(
        title_ru="x",
        executive_summary_ru="y",
        main_events=[DigestAIEntry(chat_id=999, message_id=888, title_ru="ghost")],
        igor_actions=[DigestAIAction(chat_id=999, person_or_chat_ru="ghost", action_ru="nope")],
    )
    cleaned = sanitize_ai_output(dirty, {"chats": [{"chat_id": chat.id, "messages": [{"id": message.id}]}]})
    assert cleaned.main_events == []
    assert cleaned.igor_actions == []


def test_conversation_bundle_caps_and_pre_period(db_session: Session) -> None:
    from app.services.digest_context import MAX_MESSAGES_PER_CHAT, load_conversation_bundles

    chat = _chat(db_session, external_id="cap", name="Cap")
    _msg(db_session, chat, external_id="pre", timestamp=_ts(hours=30), text="old context before period")
    for index in range(20):
        _msg(db_session, chat, external_id=f"m{index}", timestamp=_ts(hours=1, minutes=index), text=f"update {index} CPA")
    digest = _digest(db_session)
    bundles = load_conversation_bundles(db_session, digest.period, digest.items)
    selected = bundles[chat.id]
    assert len(selected) <= MAX_MESSAGES_PER_CHAT
    assert any(item["inside_period"] is False for item in selected)
    assert any(item["inside_period"] is True for item in selected)


def test_stale_analysis_not_authoritative_in_ai_payload(db_session: Session) -> None:
    from app.services.digest_ai import build_ai_payload
    from app.services.digest_context import load_conversation_bundles

    chat = _chat(db_session, external_id="staleai", name="Stale AI Chat")
    old = _msg(db_session, chat, external_id="old", timestamp=_ts(hours=3), text="old")
    _analysis(db_session, old, needs_igor=True, explanation="Старый вывод: нужен Игорь")
    _msg(db_session, chat, external_id="later", timestamp=_ts(hours=1), direction=MessageDirection.OUTGOING, text="answered")
    digest = _digest(db_session)
    item = digest.items[0]
    assert item.analysis_fresh is False
    assert item.needs_igor is False
    bundles = load_conversation_bundles(db_session, digest.period, digest.items)
    payload, _ = build_ai_payload(digest, digest.items, bundles=bundles)
    chat_payload = payload["chats"][0]
    assert chat_payload["summary_ru"] == ""
    assert chat_payload["needs_igor"] is False


def json_blob(result) -> str:
    return result.model_dump_json().lower()
