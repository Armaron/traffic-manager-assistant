import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import Platform
from app.integrations.base import MessengerAdapter
from app.integrations.mock import MockTypeXAdapter
from app.integrations.typex_errors import TypeXProtocolError
from app.models import Chat, ContactIdentity, Message
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender
from app.services.typex_sync import sync_typex_messages
from tests.typex_helpers import (
    TEST_CHAT_TOOL,
    TEST_MESSAGE_TOOL,
    session_handler,
    typex_adapter,
)


class _DownAdapter(MessengerAdapter):
    platform = Platform.TYPEX

    async def health_check(self) -> bool:
        return False

    async def get_chats(self) -> list[UnifiedChat]:
        return []

    async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
        return []

    async def get_recent_messages(self, limit: int = 50) -> list[UnifiedMessage]:
        return []

    async def get_sender(self, sender_id: str) -> UnifiedSender | None:
        return None


def test_typex_health_mock(api_client: TestClient) -> None:
    response = api_client.get("/integrations/typex/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "mock"
    assert payload["connected"] is True
    assert payload["configured"] is True
    assert payload["discovery_complete"] is True
    assert payload["sync_ready"] is True
    assert payload["sync_mode"] == "full"
    assert payload["sync_block_reason"] is None
    assert payload["missing_required_tools"] == []


def test_typex_sync_mock_success_and_idempotent(api_client: TestClient, db_session: Session) -> None:
    first = api_client.post("/integrations/typex/sync")
    assert first.status_code == 200
    payload = first.json()
    assert payload["chats_seen"] >= 1
    assert payload["messages_created"] >= 1
    created = payload["messages_created"]
    first_count = db_session.scalar(select(func.count()).select_from(Message))

    second = api_client.post("/integrations/typex/sync")
    assert second.status_code == 200
    assert second.json()["messages_created"] == 0
    assert second.json()["messages_existing"] == created
    assert db_session.scalar(select(func.count()).select_from(Message)) == first_count
    assert db_session.scalar(select(func.count()).select_from(ContactIdentity)) >= 1


def test_typex_unavailable_safe_response(monkeypatch, api_client: TestClient) -> None:
    monkeypatch.setattr("app.api.typex.get_typex_adapter", lambda: _DownAdapter())
    health = api_client.get("/integrations/typex/health")
    assert health.status_code == 200
    assert health.json()["connected"] is False
    sync = api_client.post("/integrations/typex/sync")
    assert sync.status_code == 503
    assert sync.json()["detail"] == "TypeX is not connected"


def test_sync_helper_uses_adapter(db_session: Session) -> None:
    result = asyncio.run(
        sync_typex_messages(db_session, MockTypeXAdapter(), chat_limit=20, message_limit=50)
    )
    db_session.commit()
    assert result.chats_seen >= 1
    assert result.messages_created >= 1
    again = asyncio.run(
        sync_typex_messages(db_session, MockTypeXAdapter(), chat_limit=20, message_limit=50)
    )
    db_session.commit()
    assert again.messages_created == 0
    assert again.messages_existing == result.messages_created


def test_main_health_stays_up(api_client: TestClient) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["typex_mode"] == "mock"


def test_sync_blocked_if_required_bindings_missing(monkeypatch, api_client: TestClient) -> None:
    calls: dict[str, list[dict]] = {}
    adapter = typex_adapter(
        session_handler([TEST_CHAT_TOOL, TEST_MESSAGE_TOOL], calls=calls, default_call_result=[]),
        chats_tool=None,
        messages_tool=None,
        current_user_tool=None,
    )
    monkeypatch.setattr("app.api.typex.get_typex_adapter", lambda: adapter)
    response = api_client.post("/integrations/typex/sync")
    assert response.status_code == 400
    assert response.json()["detail"] == "TypeX configuration required"
    assert calls == {}


def test_sync_blocked_if_configured_tool_not_in_discovery(
    monkeypatch, api_client: TestClient, db_session: Session
) -> None:
    adapter = typex_adapter(
        session_handler([TEST_CHAT_TOOL]),
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=TEST_MESSAGE_TOOL.name,
        current_user_tool=None,
    )
    monkeypatch.setattr("app.api.typex.get_typex_adapter", lambda: adapter)
    response = api_client.post("/integrations/typex/sync")
    assert response.status_code == 502
    assert response.json()["detail"] == "TypeX read operation failed"
    assert db_session.scalar(select(func.count()).select_from(Chat)) == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 0


def test_skipped_message_counted(db_session: Session) -> None:
    handler = session_handler(
        [TEST_CHAT_TOOL, TEST_MESSAGE_TOOL],
        call_results={
            TEST_CHAT_TOOL.name: [{"id": "tx-john", "name": "Affiliate John", "type": "direct"}],
            TEST_MESSAGE_TOOL.name: [
                {
                    "id": "ok",
                    "sender_id": "john-1",
                    "text": "hello",
                    "timestamp": "2026-08-17T10:00:00Z",
                    "is_outgoing": False,
                },
                {
                    "id": "skip",
                    "sender_id": "maybe-me",
                    "text": "???",
                    "timestamp": "2026-08-17T10:01:00Z",
                },
            ],
        },
    )
    adapter = typex_adapter(
        handler,
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=TEST_MESSAGE_TOOL.name,
        current_user_tool=None,
    )
    result = asyncio.run(sync_typex_messages(db_session, adapter, chat_limit=20, message_limit=50))
    db_session.commit()
    assert result.messages_seen == 2
    assert result.messages_skipped == 0
    assert result.messages_unknown_direction == 1
    assert result.messages_created == 2
    assert db_session.scalar(select(func.count()).select_from(Message)) == 2


def test_fatal_sync_rolls_back_transaction(monkeypatch, api_client: TestClient, db_session: Session) -> None:
    class _FatalAfterChat(MessengerAdapter):
        platform = Platform.TYPEX

        async def health_check(self) -> bool:
            return True

        async def get_chats(self) -> list[UnifiedChat]:
            return [UnifiedChat(platform=Platform.TYPEX, external_id="tx-1", name="Broken")]

        async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
            raise TypeXProtocolError("TypeX MCP unavailable")

        async def get_recent_messages(self, limit: int = 50) -> list[UnifiedMessage]:
            return []

        async def get_sender(self, sender_id: str) -> UnifiedSender | None:
            return None

    monkeypatch.setattr("app.api.typex.get_typex_adapter", lambda: _FatalAfterChat())
    response = api_client.post("/integrations/typex/sync")
    assert response.status_code == 502
    assert response.json()["detail"] == "TypeX MCP unavailable"
    assert db_session.scalar(select(func.count()).select_from(Chat)) == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 0


def test_sync_never_calls_ai(monkeypatch, api_client: TestClient) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("AI must not be called during TypeX sync")

    monkeypatch.setattr("app.ai.factory.get_ai_provider", boom)
    response = api_client.post("/integrations/typex/sync")
    assert response.status_code == 200
    assert response.json()["messages_created"] >= 1


def test_health_reports_missing_required_tools(monkeypatch, api_client: TestClient) -> None:
    adapter = typex_adapter(
        session_handler([TEST_CHAT_TOOL, TEST_MESSAGE_TOOL], default_call_result=[]),
        chats_tool=None,
        messages_tool=None,
        current_user_tool=None,
    )
    monkeypatch.setattr("app.api.typex.get_typex_adapter", lambda: adapter)
    monkeypatch.setattr(
        "app.api.typex.get_settings",
        lambda: SimpleNamespace(
            typex_mode="real",
            typex_chats_tool=None,
            typex_messages_tool=None,
            typex_current_user_tool=None,
            typex_sender_tool=None,
        ),
    )
    response = api_client.get("/integrations/typex/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "real"
    assert payload["connected"] is True
    assert payload["configured"] is False
    assert payload["discovery_complete"] is True
    assert payload["sync_ready"] is False
    assert payload["sync_mode"] == "limited"
    assert payload["warning_code"] == "message_direction_partial"
    assert payload["sync_block_reason"] == "configuration_required"
    assert payload["missing_required_tools"] == ["TYPEX_CHATS_TOOL", "TYPEX_MESSAGES_TOOL"]
    assert "session" not in payload
    assert "tools" not in payload


def test_real_typex_health_limited_sync_ready(monkeypatch, api_client: TestClient) -> None:
    adapter = typex_adapter(
        session_handler([TEST_CHAT_TOOL, TEST_MESSAGE_TOOL], default_call_result=[]),
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=TEST_MESSAGE_TOOL.name,
        current_user_tool="typex.get_me",
    )
    monkeypatch.setattr("app.api.typex.get_typex_adapter", lambda: adapter)
    monkeypatch.setattr(
        "app.api.typex.get_settings",
        lambda: SimpleNamespace(
            typex_mode="real",
            typex_chats_tool=TEST_CHAT_TOOL.name,
            typex_messages_tool=TEST_MESSAGE_TOOL.name,
            typex_current_user_tool="typex.get_me",
            typex_sender_tool=None,
        ),
    )
    response = api_client.get("/integrations/typex/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "real"
    assert payload["connected"] is True
    assert payload["configured"] is True
    assert payload["discovery_complete"] is True
    assert payload["sync_ready"] is True
    assert payload["sync_mode"] == "limited"
    assert payload["warning_code"] == "message_direction_partial"
    assert payload["sync_block_reason"] is None
    assert "session" not in payload
    assert "content" not in str(payload).lower()


def test_limited_sync_imports_unknown_direction(
    monkeypatch, api_client: TestClient, db_session: Session
) -> None:
    calls: dict[str, list[dict]] = {}
    adapter = typex_adapter(
        session_handler(
            [TEST_CHAT_TOOL, TEST_MESSAGE_TOOL],
            calls=calls,
            call_results={
                TEST_CHAT_TOOL.name: [{"id": "tx-1", "name": "Affiliate John", "type": "direct"}],
                TEST_MESSAGE_TOOL.name: [
                    {
                        "message_ref": "msg-1",
                        "send_name": "John",
                        "send_at": "2026-08-17T10:00:00Z",
                        "content": "Can you confirm the CPA?",
                    }
                ],
            },
        ),
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=TEST_MESSAGE_TOOL.name,
        current_user_tool=None,
    )
    monkeypatch.setattr("app.api.typex.get_typex_adapter", lambda: adapter)
    response = api_client.post("/integrations/typex/sync")
    assert response.status_code == 200
    payload = response.json()
    assert payload["messages_created"] == 1
    assert payload["messages_unknown_direction"] == 1
    stored = db_session.scalar(select(Message))
    assert stored is not None
    assert stored.direction.value == "unknown"
    assert stored.sender_name == "John"
    assert stored.contact_id is None
    assert db_session.scalar(select(func.count()).select_from(ContactIdentity)) == 0


def test_no_unsafe_typex_sync_bypass_settings() -> None:
    from app.config import Settings
    from app.integrations.typex_readiness import TYPEX_FULL_DIRECTION_AVAILABLE

    assert TYPEX_FULL_DIRECTION_AVAILABLE is False
    names = {name.lower() for name in Settings.model_fields}
    forbidden = {
        "allow_unsafe_typex_sync",
        "force_typex_sync",
        "ignore_direction",
        "dev_bypass",
    }
    assert names.isdisjoint(forbidden)

