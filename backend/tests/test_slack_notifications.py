"""Slack Windows notification capture ingest and security tests. Never talks to Slack."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.enums import DirectionSource, MessageDirection, Platform
from app.integrations.factory import get_slack_adapter, get_telegram_adapter, get_typex_adapter
from app.integrations.mock import MockSlackAdapter, MockTelegramAdapter, MockTypeXAdapter
from app.models import AIAnalysis, Chat, Message
from app.schemas.slack_notifications import SlackNotificationEvent
from app.services.slack_notifications import (
    ingest_slack_notification_event,
    reset_notification_capture_state,
)
from app.services.sync_runtime import get_sync_runtime, reset_sync_runtime
from app.services.translation_queue import take_pending_ids

NOTIFICATION_TOKEN = "local-cas-notification-token"
HELPER_DIR = PROJECT_ROOT / "windows-notification-listener"
FORBIDDEN_SNIPPETS = (
    "xoxc",
    "xoxd",
    "xoxp",
    "xapp-",
    "document.cookie",
    "Authorization: Bearer Slack",
    "LevelDB",
    "IndexedDB",
    "localStorage",
)


def _capture_settings(**kwargs: object) -> Settings:
    payload = {
        "slack_mode": "mock",
        "slack_notification_capture_enabled": True,
        "slack_notification_local_token": NOTIFICATION_TOKEN,
        "slack_user_token": None,
        "slack_app_token": None,
        "ai_provider": "mock",
        "typex_mode": "mock",
        "telegram_mode": "mock",
    }
    payload.update(kwargs)
    return Settings(**payload)


@pytest.fixture()
def capture_mode(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = _capture_settings()
    monkeypatch.setattr("app.services.slack_notifications.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.slack_notifications.get_settings", lambda: settings)
    monkeypatch.setattr("app.integrations.factory.get_settings", lambda: settings)
    reset_notification_capture_state()
    reset_sync_runtime()
    return settings


def _headers(token: str = NOTIFICATION_TOKEN) -> dict[str, str]:
    return {"X-TMA-Local-Token": token}


def _event(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "source": "slack_notification",
        "notification_external_id": "n_sample_dm_001",
        "received_at": "2026-04-01T10:00:00Z",
        "conversation_hint": "Partner A",
        "conversation_kind": "direct",
        "sender_name": "Partner A",
        "text": "Can you share current CPA?",
        "is_truncated": False,
        "mapping_confidence": "medium",
        "source_id": "com.tinyspeck.slackdesktop",
    }
    body.update(overrides)
    return body


def test_correct_local_token_accepted(capture_mode: Settings, api_client: TestClient) -> None:
    response = api_client.post(
        "/api/integrations/slack-notifications/events",
        json=_event(),
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["messages_created"] == 1


def test_wrong_local_token_rejected(capture_mode: Settings, api_client: TestClient) -> None:
    response = api_client.post(
        "/api/integrations/slack-notifications/events",
        json=_event(),
        headers=_headers("wrong-token"),
    )
    assert response.status_code == 401


def test_normalized_event_creates_slack_chat_and_message(
    capture_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    response = api_client.post(
        "/integrations/slack-notifications/events",
        json=_event(),
        headers=_headers(),
    )
    assert response.status_code == 200
    stored = db_session.scalars(select(Message)).one()
    chat = db_session.scalars(select(Chat)).one()
    assert stored.direction is MessageDirection.INCOMING
    assert stored.direction_source is DirectionSource.NOTIFICATION
    assert stored.sender_external_id is None
    assert stored.sender_name == "Partner A"
    assert stored.text == "Can you share current CPA?"
    assert stored.external_id == "n_sample_dm_001"
    assert chat.platform is Platform.SLACK
    assert chat.external_id == "notification:dm:partner-a"
    assert not chat.external_id.startswith(("C", "D", "G"))
    assert stored.raw_data is not None
    assert stored.raw_data["source"] == "notification_capture"
    assert stored.raw_data["ingestion_source"] == "slack_notification"
    assert stored.raw_data["timestamp_kind"] == "windows_notification"


def test_duplicate_event_idempotent(
    capture_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    first = api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    second = api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    assert first.status_code == 200
    assert second.json()["messages_existing"] == 1
    assert second.json()["messages_created"] == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_direction_incoming(capture_mode: Settings, api_client: TestClient, db_session: Session) -> None:
    api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    stored = db_session.scalars(select(Message)).one()
    assert stored.direction is MessageDirection.INCOMING
    assert stored.is_outgoing is False


def test_notification_source_metadata_preserved(
    capture_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    payload = _event(is_truncated=True, mapping_confidence="high")
    api_client.post("/integrations/slack-notifications/events", json=payload, headers=_headers())
    stored = db_session.scalars(select(Message)).one()
    assert stored.raw_data is not None
    assert stored.raw_data["notification_truncated"] is True
    assert stored.raw_data["mapping_confidence"] == "high"
    assert "xml" not in stored.raw_data
    assert "<toast" not in stored.text


def test_inbox_generation_increments(capture_mode: Settings, api_client: TestClient) -> None:
    runtime = get_sync_runtime()
    before = runtime.inbox_generation
    api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    assert runtime.inbox_generation == before + 1
    api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    assert runtime.inbox_generation == before + 1


def test_translation_can_enqueue_after_commit(capture_mode: Settings, db_session: Session) -> None:
    take_pending_ids()
    ingest_slack_notification_event(db_session, SlackNotificationEvent.model_validate(_event()))
    db_session.commit()
    pending = take_pending_ids()
    assert len(pending) == 1


def test_ai_not_automatically_invoked(
    capture_mode: Settings,
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai.mock_provider import MockAIProvider

    called = {"n": 0}

    async def wrapped(self: MockAIProvider, *args: object, **kwargs: object) -> object:
        called["n"] += 1
        raise AssertionError("OpenRouter / AI must not run on notification ingest")

    monkeypatch.setattr(MockAIProvider, "analyze_message", wrapped)
    api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    assert called["n"] == 0
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 0


def test_slack_write_not_invoked(
    capture_mode: Settings,
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def explode() -> object:
        calls.append("adapter")
        raise AssertionError("Slack SDK must not be used for notification capture")

    monkeypatch.setattr("app.integrations.factory.get_slack_adapter", explode)
    response = api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    assert response.status_code == 200
    assert calls == []


def test_typex_unaffected(capture_mode: Settings, api_client: TestClient, db_session: Session) -> None:
    before = db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TYPEX)) or 0
    api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    after = db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TYPEX)) or 0
    assert after == before
    assert isinstance(get_typex_adapter(), MockTypeXAdapter)


def test_telegram_unaffected(capture_mode: Settings, api_client: TestClient, db_session: Session) -> None:
    before = db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TELEGRAM)) or 0
    api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    after = db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TELEGRAM)) or 0
    assert after == before
    assert isinstance(get_telegram_adapter(), MockTelegramAdapter)


def test_official_slack_unaffected(capture_mode: Settings, api_client: TestClient) -> None:
    assert isinstance(get_slack_adapter(), MockSlackAdapter)
    health = api_client.get("/integrations/slack/health").json()
    assert health["mode"] == "mock"
    assert "notification" not in health["mode"]


def test_aggregate_payload_skipped(capture_mode: Settings, api_client: TestClient, db_session: Session) -> None:
    payload = _event(text="3 new messages", mapping_confidence="low")
    response = api_client.post("/integrations/slack-notifications/events", json=payload, headers=_headers())
    assert response.status_code == 200
    assert response.json()["messages_created"] == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 0


def test_heartbeat_and_health(capture_mode: Settings, api_client: TestClient) -> None:
    reset_notification_capture_state()
    ping = api_client.post(
        "/api/integrations/slack-notifications/heartbeat",
        json={"listener_access": "allowed", "slack_source_detected": True},
        headers=_headers(),
    )
    assert ping.status_code == 200
    health = api_client.get("/api/integrations/slack-notifications/health").json()
    assert health["enabled"] is True
    assert health["helper_connected"] is True
    assert health["permission_allowed"] is True
    assert health["slack_source_detected"] is True
    dumped = str(health).lower()
    assert "xoxp" not in dumped
    assert NOTIFICATION_TOKEN.lower() not in dumped


def test_disabled_capture_rejects_events(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _capture_settings(slack_notification_capture_enabled=False)
    monkeypatch.setattr("app.services.slack_notifications.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.slack_notifications.get_settings", lambda: settings)
    response = api_client.post(
        "/integrations/slack-notifications/events",
        json=_event(),
        headers=_headers(),
    )
    assert response.status_code == 409


def test_notification_makes_analysis_stale(
    capture_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    from app.ai.mock_provider import MockAIProvider
    from app.services.analysis import AIAnalysisService
    from app.services.inbox import analysis_staleness

    api_client.post("/integrations/slack-notifications/events", json=_event(), headers=_headers())
    message = db_session.scalars(select(Message)).one()
    analysis = __import__("asyncio").run(AIAnalysisService(db_session, MockAIProvider()).analyze_message(message.id))
    db_session.commit()
    later = _event(notification_external_id="n_sample_dm_002", received_at="2026-04-01T10:05:00Z", text="second")
    api_client.post("/integrations/slack-notifications/events", json=later, headers=_headers())
    assert analysis_staleness(db_session, analysis).is_stale is True


def test_analysis_prompt_marks_notification_source() -> None:
    from datetime import datetime, timezone

    from app.ai.prompts import format_analysis_user_content
    from app.enums import ChatType, ConversationStatus
    from app.schemas.analysis import AIAnalysisContext
    from app.schemas.chat import ChatRead
    from app.schemas.message import MessageRead

    ts = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    current = MessageRead(
        id=11,
        chat_id=5,
        external_id="n_sample",
        sender_external_id=None,
        sender_name="Partner A",
        contact_id=None,
        text="Can you share current CPA?",
        timestamp=ts,
        is_outgoing=False,
        created_at=ts,
        raw_data={"source": "notification_capture", "notification_truncated": True},
    )
    prompt = format_analysis_user_content(
        AIAnalysisContext(
            current_message=current,
            recent_messages=[current],
            chat=ChatRead(
                id=5,
                platform=Platform.SLACK,
                external_id="notification:dm:partner-a",
                name="Partner A",
                chat_type=ChatType.DIRECT,
                status=ConversationStatus.NEW,
                last_message_at=ts,
                created_at=ts,
                updated_at=ts,
            ),
        )
    )
    assert "Windows notification" in prompt
    assert "truncated" in prompt.lower()


def test_helper_source_has_no_slack_theft_or_notification_removal() -> None:
    files = [
        path
        for path in HELPER_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".cs", ".xaml", ".csproj", ".xml", ".ps1"}
    ]
    blob = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in files)
    lowered = blob.lower()
    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet.lower() not in lowered
    assert "removenotification" not in lowered.replace(" ", "")
    assert "clearnotifications" not in lowered.replace(" ", "")
    assert "usernotificationlistener" in lowered
    assert "requestaccessasync" in lowered


def test_backend_source_has_no_slack_session_extraction() -> None:
    files = [
        PROJECT_ROOT / "backend" / "app" / "services" / "slack_notifications.py",
        PROJECT_ROOT / "backend" / "app" / "api" / "slack_notifications.py",
        PROJECT_ROOT / "backend" / "app" / "integrations" / "slack_notification_parser.py",
        PROJECT_ROOT / "backend" / "app" / "integrations" / "slack_notification_source.py",
    ]
    blob = "\n".join(path.read_text(encoding="utf-8") for path in files)
    lowered = blob.lower()
    for snippet in ("xoxp", "xapp-", "document.cookie", "leveldb", "indexeddb"):
        assert snippet not in lowered
    assert "removenotification" not in lowered
    assert "clearnotifications" not in lowered
    assert Path(files[0]).is_file()
