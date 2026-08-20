"""Russian translation is metadata. It must never block messenger sync or change AI state."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.errors import (
    AIAuthenticationError,
    AIInsufficientBalanceError,
    AIRateLimitError,
    AIResponseValidationError,
    AIUnavailableError,
)
from app.ai.translation_prompt import TRANSLATION_SYSTEM_PROMPT
from app.ai.translation_provider import MockTranslationEngine, OpenRouterTranslationEngine
from app.ai.translation_schema import TranslationResult
from app.config import Settings
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
from app.models import AIAnalysis, Chat, Message
from app.schemas.inbox import SlackSyncResult, TelegramSyncResult, TypeXSyncResult
from app.schemas.unified import UnifiedMessage
from app.services.inbox import analysis_staleness
from app.services.message_ingestion import MessageIngestionService
from app.services.message_translation import async_translate_message, public_translation, translation_for
from app.services.sync_runtime import SyncPlatform, get_sync_runtime, reset_sync_runtime
from app.services.translation_detect import needs_translation, skip_reason, source_text_hash
from app.services.translation_queue import (
    enqueue_message_ids,
    flush_pending_translations,
    note_message_id,
    take_pending_ids,
)


def _ts(minute: int = 0) -> datetime:
    return datetime(2026, 8, 18, 12, minute, tzinfo=timezone.utc)


def _cfg() -> Settings:
    return Settings(
        translation_provider="mock",
        translation_min_text_length=4,
        translation_max_chars=6000,
        auto_translate_enabled=True,
    )


class RecordingEngine:
    name = "mock"
    model = "rec-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.texts: list[str] = []

    async def translate(self, text: str) -> TranslationResult:
        self.calls += 1
        self.texts.append(text)
        return TranslationResult(source_language="en", translated_text=f"RU: {text}")


class FailingEngine:
    name = "mock"
    model = "fail"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    async def translate(self, text: str) -> TranslationResult:
        self.calls += 1
        raise self.exc


def _add_message(
    session: Session,
    text: str,
    *,
    platform: Platform = Platform.TYPEX,
    external_id: str = "m-1",
    chat_external: str = "chat-1",
    direction: MessageDirection = MessageDirection.INCOMING,
    thread_external_id: str | None = None,
) -> Message:
    chat = session.scalar(
        select(Chat).where(Chat.platform == platform, Chat.external_id == chat_external)
    )
    if chat is None:
        chat = Chat(
            platform=platform,
            external_id=chat_external,
            name="Partner",
            chat_type=ChatType.DIRECT,
            status=ConversationStatus.NEW,
        )
        session.add(chat)
        session.flush()
    message = Message(
        chat_id=chat.id,
        external_id=external_id,
        sender_name="Eduard",
        text=text,
        timestamp=_ts(),
        direction=direction,
        direction_source=DirectionSource.NATIVE,
        thread_external_id=thread_external_id,
    )
    session.add(message)
    session.commit()
    session.refresh(message)
    return message


def test_russian_text_skipped() -> None:
    assert skip_reason("Привет, сможете проверить CPA?", _cfg()) is not None
    assert needs_translation("Привет, сможете проверить CPA?", _cfg()) is False


def test_english_chinese_turkish_need_translation() -> None:
    cfg = _cfg()
    assert needs_translation("Can you check CPA?", cfg) is True
    assert needs_translation("你好，可以看一下吗？", cfg) is True
    assert needs_translation("Selam, bakabilir misin?", cfg) is True


def test_noise_is_skipped() -> None:
    cfg = _cfg()
    assert skip_reason("👍", cfg) is not None
    assert skip_reason("😂🔥", cfg) is not None
    assert skip_reason("https://example.com/stats", cfg) is not None
    assert skip_reason("42", cfg) is not None
    assert skip_reason("OK", cfg) is not None
    assert skip_reason("ok", cfg) is not None
    assert skip_reason("[Photo]", cfg) is not None
    assert skip_reason("[File]", cfg) is not None
    assert skip_reason("[Voice message]", cfg) is not None
    assert skip_reason("Image ×4 not downloaded yet", cfg) is not None


def test_ack_sentence_is_translated() -> None:
    assert needs_translation("Ok, please increase CPA to $25", _cfg()) is True


def test_cache_and_source_hash(db_session: Session) -> None:
    async def scenario() -> None:
        engine = RecordingEngine()
        message = _add_message(db_session, "Can you send me current CPA for Indonesia?")
        original = message.text
        first = await async_translate_message(db_session, message, engine=engine, settings=_cfg())
        db_session.commit()
        assert message.text == original
        assert first.status is TranslationStatus.COMPLETED
        assert first.translated_text == "RU: Can you send me current CPA for Indonesia?"
        assert engine.calls == 1

        second = await async_translate_message(db_session, message, engine=engine, settings=_cfg())
        db_session.commit()
        assert second.id == first.id
        assert engine.calls == 1

        other = Settings(translation_provider="mock", translation_target_language="de")
        third = await async_translate_message(db_session, message, engine=engine, settings=other)
        db_session.commit()
        assert third.target_language == "de"
        assert engine.calls == 2
        assert third.id != first.id

    asyncio.run(scenario())


def test_source_edit_invalidates_translation(db_session: Session) -> None:
    async def scenario() -> None:
        engine = RecordingEngine()
        ingestion = MessageIngestionService(db_session)
        payload = UnifiedMessage(
            platform=Platform.SLACK,
            external_id="1710000000.000100",
            chat_id="D333",
            chat_name="Jacqueline",
            sender_name="Jacqueline",
            text="Can you do CPA 20?",
            timestamp=_ts(),
            direction=MessageDirection.INCOMING,
        )
        message, _created = ingestion.ingest_message(payload)
        db_session.commit()
        await async_translate_message(db_session, message, engine=engine, settings=_cfg())
        db_session.commit()
        assert engine.calls == 1

        edited = payload.model_copy(update={"text": "Can you do CPA 25?"})
        updated, created = ingestion.ingest_message(edited)
        db_session.commit()
        assert created is False
        assert updated.text == "Can you do CPA 25?"
        row = translation_for(updated)
        assert row is None or row.source_text_hash != source_text_hash("Can you do CPA 25?")
        shown = public_translation(updated, row)
        assert shown is None

        fresh = await async_translate_message(db_session, updated, engine=engine, settings=_cfg())
        db_session.commit()
        assert engine.calls == 2
        assert fresh.translated_text == "RU: Can you do CPA 25?"
        assert "CPA 20" not in (fresh.translated_text or "")

    asyncio.run(scenario())


def test_russian_edit_skips_provider(db_session: Session) -> None:
    async def scenario() -> None:
        engine = RecordingEngine()
        message = _add_message(db_session, "Can you check CPA?")
        await async_translate_message(db_session, message, engine=engine, settings=_cfg())
        db_session.commit()
        message.text = "Привет, сможете проверить CPA?"
        db_session.commit()
        row = await async_translate_message(db_session, message, engine=engine, settings=_cfg())
        db_session.commit()
        assert row.status is TranslationStatus.SKIPPED
        assert engine.calls == 1
        shown = public_translation(message, row)
        assert shown is None or shown.status is TranslationStatus.SKIPPED
        assert shown is None or shown.translated_text is None

    asyncio.run(scenario())


def test_failures_preserve_original(db_session: Session) -> None:
    async def scenario() -> None:
        message = _add_message(db_session, "Please send current CPA")
        original = message.text
        cases = [
            AIUnavailableError("AI provider unavailable"),
            AIAuthenticationError("OpenRouter authentication failed"),
            AIInsufficientBalanceError("OpenRouter balance insufficient"),
            AIRateLimitError("AI rate limit reached"),
            AIResponseValidationError("AI provider unavailable"),
        ]
        for exc in cases:
            row = await async_translate_message(
                db_session,
                message,
                engine=FailingEngine(exc),
                settings=_cfg(),
                force=True,
            )
            db_session.commit()
            db_session.refresh(message)
            assert message.text == original
            assert row.status is TranslationStatus.FAILED
            assert get_sync_runtime().state(SyncPlatform.TYPEX).last_error_code is None
            assert get_sync_runtime().state(SyncPlatform.TELEGRAM).last_error_code is None
            assert get_sync_runtime().state(SyncPlatform.SLACK).last_error_code is None

    asyncio.run(scenario())


def test_openrouter_429_is_not_busy_looped() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "rate"}})

    engine = OpenRouterTranslationEngine(
        api_key="test-key",
        model="google/gemini-3.1-flash-lite",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AIRateLimitError):
        asyncio.run(engine.translate("Can you check CPA?"))
    assert calls["n"] == 1


def test_openrouter_timeout_retries_once() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.TimeoutException("slow")

    engine = OpenRouterTranslationEngine(
        api_key="test-key",
        model="google/gemini-3.1-flash-lite",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AIUnavailableError):
        asyncio.run(engine.translate("Can you check CPA?"))
    assert calls["n"] == 2


def test_translation_payload_is_text_only() -> None:
    engine = OpenRouterTranslationEngine(api_key="test-key", model="google/gemini-3.1-flash-lite")
    payload = engine.build_payload("Can we increase CPA to $25 for ID?")
    assert payload["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert payload["messages"][0]["content"] == TRANSLATION_SYSTEM_PROMPT
    assert payload["messages"][1]["content"] == "Can we increase CPA to $25 for ID?"
    blob = str(payload)
    assert "needs_reply" not in blob
    assert "draft_reply" not in blob


def test_messenger_sync_does_not_await_translation(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def boom(*_args: object, **_kwargs: object) -> object:
        calls.append("translate")
        await asyncio.sleep(30)
        raise AssertionError("translation must not run inside sync")

    monkeypatch.setattr("app.services.message_translation.async_translate_message", boom)

    from app.integrations.mock import MockSlackAdapter, MockTelegramAdapter, MockTypeXAdapter
    from app.services.platform_sync import run_slack_sync, run_telegram_sync, run_typex_sync

    async def scenario() -> None:
        started = perf_counter()
        typex = await run_typex_sync(db_session, adapter=MockTypeXAdapter(), settings=_cfg())
        telegram = await run_telegram_sync(db_session, adapter=MockTelegramAdapter(), settings=_cfg())
        slack = await run_slack_sync(db_session, adapter=MockSlackAdapter(), settings=_cfg())
        db_session.commit()
        elapsed = perf_counter() - started
        assert elapsed < 5
        assert calls == []
        assert isinstance(typex, TypeXSyncResult)
        assert isinstance(telegram, TelegramSyncResult)
        assert isinstance(slack, SlackSyncResult)
        assert db_session.scalar(select(Message)) is not None

    asyncio.run(scenario())


def test_slack_ack_does_not_wait_for_translation(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.integrations.slack import SlackAdapter
    from app.services.slack_events import SlackEventService
    from tests.slack_helpers import FakeSlackClient, incoming_message, sample_im

    calls: list[str] = []

    async def boom(*_args: object, **_kwargs: object) -> object:
        calls.append("translate")
        await asyncio.sleep(30)
        return None

    monkeypatch.setattr("app.services.message_translation.async_translate_message", boom)
    reader = FakeSlackClient(conversations=[sample_im()], history={"D333": []})
    adapter = SlackAdapter(reader, chat_limit=10, message_limit=20, download_files=False)
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)

    async def scenario() -> None:
        acks: list[str] = []

        async def ack() -> None:
            acks.append("ok")

        service = SlackEventService(
            settings=Settings(slack_mode="mock", auto_sync_enabled=True),
            adapter_factory=lambda: adapter,
            session_factory=lambda: factory(),
        )
        await service.start()
        try:
            await service.handle_envelope(
                "env-1",
                {"event": incoming_message(ts="1710000999.000001", text="Can we raise CPA?")},
                ack,
            )
            assert acks == ["ok"]
            assert calls == []
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_translation_does_not_touch_ai_or_direction(db_session: Session) -> None:
    async def scenario() -> None:
        reset_sync_runtime()
        runtime = get_sync_runtime()
        inbox_before = runtime.inbox_generation
        message = _add_message(db_session, "Can you send current CPA?", direction=MessageDirection.INCOMING)
        analysis = AIAnalysis(
            message_id=message.id,
            summary="CPA request",
            request="Send CPA",
            category=AnalysisCategory.AFFILIATE,
            priority=Priority.NORMAL,
            needs_reply=True,
            needs_igor=False,
            reason="Partner asked for CPA",
            draft_reply="Hi, current CPA is $25.",
            provider="mock",
            model="mock",
        )
        db_session.add(analysis)
        db_session.commit()
        stale_before = analysis_staleness(db_session, analysis)
        await async_translate_message(db_session, message, engine=RecordingEngine(), settings=_cfg())
        db_session.commit()
        db_session.refresh(message)
        db_session.refresh(analysis)
        stale_after = analysis_staleness(db_session, analysis)
        assert stale_before.is_stale is False
        assert stale_after.is_stale is False
        assert analysis.needs_reply is True
        assert analysis.draft_reply == "Hi, current CPA is $25."
        assert message.direction is MessageDirection.INCOMING
        assert runtime.inbox_generation == inbox_before

    asyncio.run(scenario())


def test_platforms_and_captions_and_threads(db_session: Session) -> None:
    async def scenario() -> None:
        engine = RecordingEngine()
        typex = _add_message(db_session, "Need current CPA for ID", platform=Platform.TYPEX, chat_external="tx")
        telegram = _add_message(
            db_session,
            "Please check this GEO screenshot",
            platform=Platform.TELEGRAM,
            chat_external="tg",
            external_id="tg-1",
        )
        slack = _add_message(
            db_session,
            "Can we raise CPA?",
            platform=Platform.SLACK,
            chat_external="D333",
            external_id="171.1",
        )
        thread = _add_message(
            db_session,
            "Yes, for Indonesia",
            platform=Platform.SLACK,
            chat_external="D333",
            external_id="171.2",
            thread_external_id="171.1",
        )
        unknown = _add_message(
            db_session,
            "What is current FTD?",
            platform=Platform.TYPEX,
            chat_external="tx",
            external_id="tx-unk",
            direction=MessageDirection.UNKNOWN,
        )
        outgoing = _add_message(
            db_session,
            "I will check CPA now",
            platform=Platform.TELEGRAM,
            chat_external="tg",
            external_id="tg-out",
            direction=MessageDirection.OUTGOING,
        )
        for item in (typex, telegram, slack, thread, unknown, outgoing):
            row = await async_translate_message(db_session, item, engine=engine, settings=_cfg())
            assert row.status is TranslationStatus.COMPLETED
            assert item.text != row.translated_text
            shown = public_translation(item, row)
            assert shown is not None
            assert shown.translated_text
            assert shown.status is TranslationStatus.COMPLETED
        photo = _add_message(
            db_session, "[Photo]", platform=Platform.TELEGRAM, chat_external="tg", external_id="tg-photo"
        )
        skipped = await async_translate_message(db_session, photo, engine=engine, settings=_cfg())
        assert skipped.status is TranslationStatus.SKIPPED

    asyncio.run(scenario())


def test_too_long_is_skipped(db_session: Session) -> None:
    async def scenario() -> None:
        engine = RecordingEngine()
        message = _add_message(db_session, "CPA " + ("x" * 7000))
        row = await async_translate_message(db_session, message, engine=engine, settings=_cfg())
        assert row.status is TranslationStatus.SKIPPED
        assert row.error_code == "too_long"
        assert engine.calls == 0

    asyncio.run(scenario())


def test_flush_is_non_blocking() -> None:
    take_pending_ids()
    note_message_id(1)
    note_message_id(1)
    assert take_pending_ids() == [1]
    assert flush_pending_translations() == 0


def test_queue_is_bounded() -> None:
    from app.services import translation_queue as queue_mod

    async def scenario() -> None:
        previous = queue_mod._queue
        queued_ids = set(queue_mod._queued_ids)
        inflight = set(queue_mod._inflight_ids)
        queue_mod._queue = asyncio.Queue(maxsize=1)
        queue_mod._queued_ids.clear()
        queue_mod._inflight_ids.clear()
        try:
            queue_mod._queue.put_nowait(11)
            queue_mod._queued_ids.add(11)
            queued = enqueue_message_ids([12, 13], auto=True)
            assert queued == 0
        finally:
            queue_mod._queue = previous
            queue_mod._queued_ids.clear()
            queue_mod._queued_ids.update(queued_ids)
            queue_mod._inflight_ids.clear()
            queue_mod._inflight_ids.update(inflight)

    asyncio.run(scenario())


def test_duplicate_enqueue_is_skipped() -> None:
    from app.services import translation_queue as queue_mod

    async def scenario() -> None:
        previous = queue_mod._queue
        queued_ids = set(queue_mod._queued_ids)
        inflight = set(queue_mod._inflight_ids)
        queue_mod._queue = asyncio.Queue(maxsize=10)
        queue_mod._queued_ids.clear()
        queue_mod._inflight_ids.clear()
        try:
            assert enqueue_message_ids([7, 7, 8], auto=True) == 2
            assert enqueue_message_ids([7, 8, 9], auto=True) == 1
            assert queue_mod._queue.qsize() == 3
        finally:
            queue_mod._queue = previous
            queue_mod._queued_ids.clear()
            queue_mod._queued_ids.update(queued_ids)
            queue_mod._inflight_ids.clear()
            queue_mod._inflight_ids.update(inflight)

    asyncio.run(scenario())


def test_concurrent_same_message_uses_unique_row(db_session: Session) -> None:
    async def scenario() -> None:
        message = _add_message(db_session, "Can you send current CPA for ID?")
        engine = RecordingEngine()
        first = await async_translate_message(db_session, message, engine=engine, settings=_cfg())
        db_session.commit()
        second = await async_translate_message(db_session, message, engine=engine, settings=_cfg())
        db_session.commit()
        assert first.id == second.id
        assert engine.calls == 1

    asyncio.run(scenario())


def test_manual_translate_api(api_client: TestClient, db_session: Session) -> None:
    message = _add_message(db_session, "Can you send me current CPA for Indonesia?")
    response = api_client.post(f"/messages/{message.id}/translate", json={"force": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "Can you send me current CPA for Indonesia?"
    assert payload["translation"]["status"] == "completed"
    assert payload["translation"]["translated_text"].startswith("RU:")
    assert "provider" not in payload["translation"]
    assert "error_code" not in payload["translation"]

    listed = api_client.get(f"/chats/{message.chat_id}/messages").json()
    match = next(item for item in listed if item["id"] == message.id)
    assert match["translation"]["translated_text"] == payload["translation"]["translated_text"]

    queued = api_client.post(f"/chats/{message.chat_id}/translations/queue")
    assert queued.status_code == 200
    assert queued.json()["queued"] == 0


def test_mock_engine_prefix() -> None:
    result = asyncio.run(MockTranslationEngine().translate("Hello"))
    assert result.translated_text == "RU: Hello"


def test_worker_process_does_not_raise_pending_rollback(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import PendingRollbackError
    from sqlalchemy.orm import sessionmaker

    from app.services import translation_queue as queue_mod

    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(queue_mod, "get_session_factory", lambda: factory)
    message = _add_message(db_session, "Can you send current CPA for ID?")
    original_load = queue_mod.load_translation_work

    def explode(*_args, **_kwargs):
        raise PendingRollbackError(
            "This Session's transaction has been rolled back due to a previous "
            "exception during flush. Original exception was: database is locked",
        )

    monkeypatch.setattr(queue_mod, "load_translation_work", explode)
    asyncio.run(queue_mod._process(message.id))

    monkeypatch.setattr(queue_mod, "load_translation_work", original_load)
    monkeypatch.setattr(queue_mod, "apply_translation_work", explode)
    asyncio.run(queue_mod._process(message.id))
