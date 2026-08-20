"""Slack Browser Reader ingest and security tests. Never talks to Slack."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.enums import MessageDirection, Platform
from app.integrations.factory import get_slack_adapter, get_telegram_adapter, get_typex_adapter
from app.integrations.mock import MockTelegramAdapter, MockTypeXAdapter
from app.integrations.slack_errors import SlackConfigurationError
from app.models import AIAnalysis, Chat, Message
from app.schemas.slack_browser import SlackBrowserConversation, SlackBrowserEventsPayload, SlackBrowserMessage
from app.services.slack_browser import ingest_slack_browser_events
from app.services.sync_runtime import get_sync_runtime, reset_sync_runtime
from app.services.translation_queue import take_pending_ids

BROWSER_TOKEN = "local-cas-browser-token"
EXTENSION_DIR = PROJECT_ROOT / "browser-extension" / "slack-reader"
FORBIDDEN_PERMISSIONS = {
    "cookies",
    "webRequest",
    "webRequestBlocking",
    "debugger",
    "history",
    "tabs",
    "nativeMessaging",
}
FORBIDDEN_SNIPPETS = (
    "document.cookie",
    "chrome.cookies",
    "xoxc",
    "xoxd",
    "xoxp",
    "xapp-",
)


def _browser_settings(**kwargs: object) -> Settings:
    payload = {
        "slack_mode": "browser",
        "slack_browser_local_token": BROWSER_TOKEN,
        "slack_user_token": None,
        "slack_app_token": None,
        "ai_provider": "mock",
    }
    payload.update(kwargs)
    return Settings(**payload)


@pytest.fixture()
def browser_mode(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = _browser_settings()
    monkeypatch.setattr("app.services.slack_browser.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.slack_browser.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.slack.get_settings", lambda: settings)
    monkeypatch.setattr("app.integrations.factory.get_settings", lambda: settings)
    return settings


def _headers(token: str = BROWSER_TOKEN, origin: str | None = "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") -> dict[str, str]:
    headers = {"X-CAS-Slack-Browser-Token": token}
    if origin:
        headers["Origin"] = origin
    return headers


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "conversation": {"external_id": "C0OFFERS1", "name": "offers", "type": "channel"},
        "messages": [
            {
                "external_id": "1710000900.000100",
                "sender_external_id": "U222AAA",
                "sender_name": "Alex Partner",
                "timestamp": "1710000900.000100",
                "text": "Need a higher CPA for KR",
                "direction": "incoming",
                "thread_external_id": None,
            }
        ],
    }
    body.update(overrides)
    return body


def test_local_token_required(browser_mode: Settings, api_client: TestClient) -> None:
    response = api_client.post("/integrations/slack-browser/events", json=_payload())
    assert response.status_code == 401


def test_wrong_local_token_rejected(browser_mode: Settings, api_client: TestClient) -> None:
    response = api_client.post(
        "/integrations/slack-browser/events",
        json=_payload(),
        headers=_headers("wrong-token"),
    )
    assert response.status_code == 401


def test_slack_page_origin_rejected(browser_mode: Settings, api_client: TestClient) -> None:
    response = api_client.post(
        "/integrations/slack-browser/events",
        json=_payload(),
        headers=_headers(origin="https://app.slack.com"),
    )
    assert response.status_code == 403


def test_normalized_message_ingested(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    reset_sync_runtime()
    response = api_client.post(
        "/integrations/slack-browser/events",
        json=_payload(),
        headers=_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["messages_created"] == 1
    stored = db_session.scalars(select(Message)).one()
    assert stored.external_id == "1710000900.000100"
    assert stored.direction is MessageDirection.INCOMING
    assert stored.text == "Need a higher CPA for KR"
    chat = db_session.scalars(select(Chat)).one()
    assert chat.platform is Platform.SLACK
    assert chat.external_id == "C0OFFERS1"


def test_noise_only_payload_does_not_rename_existing_chat(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    reset_sync_runtime()
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=_headers())
    noise = _payload()
    noise["conversation"] = {"external_id": "C0OFFERS1", "name": "general", "type": "channel"}
    noise["messages"] = [
        {
            "external_id": "b_today",
            "sender_external_id": None,
            "sender_name": "Unknown",
            "timestamp": "1710000900.000100",
            "text": "Today",
            "direction": "unknown",
        }
    ]
    response = api_client.post("/integrations/slack-browser/events", json=noise, headers=_headers())
    assert response.status_code == 200
    chat = db_session.scalars(select(Chat)).one()
    assert chat.external_id == "C0OFFERS1"
    assert chat.name == "offers"


def test_different_conversation_ids_create_separate_chats(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    reset_sync_runtime()
    first = _payload()
    second = _payload()
    second["conversation"] = {"external_id": "D0ACTIVE1", "name": "Alex Partner", "type": "direct"}
    second["messages"][0]["external_id"] = "1710002800.000100"
    second["messages"][0]["timestamp"] = "1710002800.000100"
    api_client.post("/integrations/slack-browser/events", json=first, headers=_headers())
    api_client.post("/integrations/slack-browser/events", json=second, headers=_headers())
    chats = db_session.scalars(select(Chat).order_by(Chat.external_id)).all()
    assert [chat.external_id for chat in chats] == ["C0OFFERS1", "D0ACTIVE1"]
    assert {chat.name for chat in chats} == {"offers", "Alex Partner"}


def test_date_divider_payloads_are_skipped(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    reset_sync_runtime()
    body = _payload()
    real = body["messages"][0]
    body["messages"] = [
        {
            **real,
            "external_id": "b_today",
            "sender_external_id": None,
            "sender_name": "Unknown",
            "text": "Today",
            "direction": "unknown",
        },
        {
            **real,
            "external_id": "b_chrome",
            "sender_name": "Adam Scott",
            "text": "Adam Scott 11:26 AM can use anything",
            "direction": "incoming",
        },
    ]
    response = api_client.post("/integrations/slack-browser/events", json=body, headers=_headers())
    assert response.status_code == 200
    assert response.json()["messages_created"] == 1
    stored = db_session.scalars(select(Message)).one()
    assert stored.external_id == "b_chrome"
    assert stored.text == "can use anything"
    assert stored.sender_name == "Adam Scott"


def test_duplicate_event_idempotent(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    headers = _headers()
    first = api_client.post("/integrations/slack-browser/events", json=_payload(), headers=headers)
    second = api_client.post("/integrations/slack-browser/events", json=_payload(), headers=headers)
    assert first.status_code == 200
    assert second.json()["messages_existing"] == 1
    assert second.json()["messages_created"] == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_message_edit_updates_row(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    headers = _headers()
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=headers)
    edited = _payload()
    edited["messages"][0]["text"] = "Updated: CPA can be 1.4"
    response = api_client.post("/integrations/slack-browser/events", json=edited, headers=headers)
    assert response.json()["messages_updated"] == 1
    stored = db_session.scalars(select(Message)).one()
    assert stored.text == "Updated: CPA can be 1.4"
    assert stored.external_id == "1710000900.000100"


def test_browser_event_increments_inbox_generation(
    browser_mode: Settings,
    api_client: TestClient,
) -> None:
    reset_sync_runtime()
    runtime = get_sync_runtime()
    before = runtime.inbox_generation
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=_headers())
    assert runtime.inbox_generation == before + 1
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=_headers())
    assert runtime.inbox_generation == before + 1


def test_browser_event_does_not_call_ai(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai.mock_provider import MockAIProvider

    called = {"n": 0}

    async def wrapped(self: MockAIProvider, *args: object, **kwargs: object) -> object:
        called["n"] += 1
        raise AssertionError("OpenRouter / AI must not run on browser ingest")

    monkeypatch.setattr(MockAIProvider, "analyze_message", wrapped)
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=_headers())
    assert called["n"] == 0
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 0


def test_browser_event_does_not_send_slack(
    browser_mode: Settings,
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def explode() -> object:
        calls.append("adapter")
        raise AssertionError("Slack SDK must not be used in browser ingest")

    monkeypatch.setattr("app.integrations.factory.get_slack_adapter", explode)
    monkeypatch.setattr("app.api.slack_browser.get_slack_adapter", explode, raising=False)
    response = api_client.post("/integrations/slack-browser/events", json=_payload(), headers=_headers())
    assert response.status_code == 200
    assert calls == []


def test_removal_event_never_deletes_message(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    headers = _headers()
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=headers)
    empty = _payload(messages=[])
    api_client.post("/integrations/slack-browser/events", json=empty, headers=headers)
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_no_slack_api_credential_required_in_browser_mode(
    browser_mode: Settings,
    api_client: TestClient,
) -> None:
    health = api_client.get("/integrations/slack/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["mode"] == "browser"
    assert payload["authenticated"] is False
    assert payload["socket_configured"] is False
    dumped = str(payload).lower()
    assert "xoxp" not in dumped
    assert "xapp" not in dumped
    with pytest.raises(SlackConfigurationError):
        get_slack_adapter()


def test_heartbeat_sets_connected(browser_mode: Settings, api_client: TestClient) -> None:
    reset_sync_runtime()
    response = api_client.post(
        "/integrations/slack-browser/heartbeat",
        json={"workspace_present": True},
        headers=_headers(),
    )
    assert response.status_code == 200
    health = api_client.get("/integrations/slack/health").json()
    assert health["browser_connected"] is True
    assert health["workspace_present"] is True


def test_spec_api_prefix_events(browser_mode: Settings, api_client: TestClient) -> None:
    response = api_client.post(
        "/api/integrations/slack-browser/events",
        json=_payload(),
        headers=_headers(),
    )
    assert response.status_code == 200


def test_visible_deleted_updates_text_not_row(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    headers = _headers()
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=headers)
    deleted = _payload()
    deleted["messages"][0]["text"] = "This message was deleted"
    deleted["messages"][0]["deleted"] = True
    api_client.post("/integrations/slack-browser/events", json=deleted, headers=headers)
    stored = db_session.scalars(select(Message)).one()
    assert stored.text == "[Deleted Slack message]"
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_fallback_ids_do_not_collide_with_slack_ts(db_session: Session) -> None:
    payload = SlackBrowserEventsPayload(
        conversation=SlackBrowserConversation(external_id="C0FALLBACK", name="fallback", type="channel"),
        messages=[
            SlackBrowserMessage(
                external_id="b_abc123",
                sender_external_id="U222AAA",
                sender_name="Alex Partner",
                timestamp="2024-03-09T12:00:00+00:00",
                text="No Slack ts on this node",
                direction="incoming",
                browser_fallback_id=True,
            )
        ],
    )
    ingest_slack_browser_events(db_session, payload)
    db_session.commit()
    stored = db_session.scalars(select(Message)).one()
    assert stored.raw_data is not None
    assert stored.raw_data.get("browser_fallback_id") is True
    assert stored.raw_data.get("source") == "browser"
    assert "html" not in stored.raw_data
    assert "<div" not in stored.text


def test_browser_message_makes_analysis_stale(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    from app.ai.mock_provider import MockAIProvider
    from app.services.analysis import AIAnalysisService
    from app.services.inbox import analysis_staleness

    headers = _headers()
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=headers)
    message = db_session.scalars(select(Message)).one()
    analysis = __import__("asyncio").run(AIAnalysisService(db_session, MockAIProvider()).analyze_message(message.id))
    db_session.commit()
    later = _payload()
    later["messages"][0]["external_id"] = "1710000900.000200"
    later["messages"][0]["timestamp"] = "1710000900.000200"
    later["messages"][0]["text"] = "second"
    api_client.post("/integrations/slack-browser/events", json=later, headers=headers)
    assert analysis_staleness(db_session, analysis).is_stale is True


def test_extension_manifest_permissions() -> None:
    import json

    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert manifest["host_permissions"] == ["https://app.slack.com/*"]
    assert set(manifest["permissions"]) <= {"storage"}
    for permission in FORBIDDEN_PERMISSIONS:
        assert permission not in manifest["permissions"]
        assert permission not in manifest.get("optional_permissions", [])
        assert permission not in manifest.get("host_permissions", [])


def test_extension_source_has_no_credential_theft() -> None:
    files = [
        EXTENSION_DIR / "manifest.json",
        EXTENSION_DIR / "background.js",
        EXTENSION_DIR / "content-script.js",
        EXTENSION_DIR / "slackDomParser.js",
        EXTENSION_DIR / "popup.js",
        EXTENSION_DIR / "popup.html",
    ]
    blob = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet not in blob
    assert "document.cookie" not in blob
    assert "chrome.cookies" not in blob
    assert "localStorage" not in blob
    assert "Authorization" not in blob
    assert "webRequest" not in blob
    assert "chrome.debugger" not in blob
    assert "MutationObserver" in blob
    assert "message-list" in blob
    manifest_text = (EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8")
    assert "all_frames" not in manifest_text
    content = (EXTENSION_DIR / "content-script.js").read_text(encoding="utf-8")
    assert "window.top !== window.self" in content
    assert "findMessagePane" in content
    assert "activeConversationId" in content
    assert "attachPaneObserver" in content
    assert "conversation-change" in content
    assert "capture-now" in content
    assert "autoCapture" in content
    assert "slack-browser-heartbeat" in content
    assert "semanticFingerprint" in content
    assert "isSemanticMutation" in content
    parser = (EXTENSION_DIR / "slackDomParser.js").read_text(encoding="utf-8")
    assert "findCanonicalMessageRoots" in parser
    assert "sanitizeCurrentSlackDom" in parser
    assert "characterData: false" in content
    assert "observer.observe(root" not in content
    assert "paneObserver.observe(pane" in content


def test_translation_can_enqueue_after_browser_commit(browser_mode: Settings, db_session: Session) -> None:
    take_pending_ids()
    ingest_slack_browser_events(db_session, SlackBrowserEventsPayload.model_validate(_payload()))
    db_session.commit()
    pending = take_pending_ids()
    assert len(pending) == 1


def test_typex_unaffected_by_browser_ingest(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    before = db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TYPEX)) or 0
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=_headers())
    after = db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TYPEX)) or 0
    assert after == before
    assert isinstance(get_typex_adapter(), MockTypeXAdapter)


def test_telegram_unaffected_by_browser_ingest(
    browser_mode: Settings,
    api_client: TestClient,
    db_session: Session,
) -> None:
    before = db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TELEGRAM)) or 0
    api_client.post("/integrations/slack-browser/events", json=_payload(), headers=_headers())
    after = db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.TELEGRAM)) or 0
    assert after == before
    assert isinstance(get_telegram_adapter(), MockTelegramAdapter)
