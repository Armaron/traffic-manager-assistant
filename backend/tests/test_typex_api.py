import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import Platform
from app.integrations.base import MessengerAdapter
from app.integrations.mock import MockTypeXAdapter
from app.models import ContactIdentity, Message
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender
from app.services.typex_sync import sync_typex_messages


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
