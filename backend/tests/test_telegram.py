import asyncio
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ChatType, Platform
from app.integrations.factory import get_telegram_adapter
from app.integrations.mock import MockTelegramAdapter
from app.integrations.telegram import TelegramAdapter
from app.integrations.telegram_client import TelethonReadClient
from app.integrations.telegram_errors import (
    TelegramAuthorizationError,
    TelegramConfigurationError,
    TelegramRateLimitError,
)
from app.integrations.telegram_mapping import (
    TelegramMessageRecord,
    canonical_peer_id,
    map_dialog,
    map_message,
)
from app.models import Chat, Contact, ContactIdentity, Message
from app.services.telegram_sync import sync_telegram_messages
from tests.telegram_helpers import (
    FakeTelegramReadClient,
    incoming_private,
    outgoing_private,
    sample_channel_dialog,
    sample_group_dialog,
    sample_private_dialog,
    sample_supergroup_dialog,
    ts,
)

FORBIDDEN_ADAPTER_METHODS = {
    "send_message",
    "send_file",
    "forward_messages",
    "edit_message",
    "delete_messages",
    "mark_read",
    "send_reaction",
    "join",
    "leave",
    "invite",
    "block",
    "mute",
    "archive",
    "pin",
    "create_chat",
    "add_contact",
    "reply",
}


def _public_methods(cls: type) -> set[str]:
    return {
        name
        for name in dir(cls)
        if not name.startswith("_") and callable(getattr(cls, name, None))
    }


def test_telegram_health_mock(api_client: TestClient) -> None:
    response = api_client.get("/integrations/telegram/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "mock"
    assert payload["configured"] is True
    assert payload["connected"] is True
    assert payload["authorized"] is True
    assert payload["sync_ready"] is True
    assert payload["missing_configuration"] == []
    assert "api_hash" not in payload
    assert "phone" not in payload
    assert "session" not in payload


def test_telegram_sync_mock_success_and_idempotent(api_client: TestClient, db_session: Session) -> None:
    first = api_client.post("/integrations/telegram/sync")
    assert first.status_code == 200
    payload = first.json()
    assert payload["chats_seen"] >= 1
    assert payload["messages_created"] >= 1
    created = payload["messages_created"]
    first_count = db_session.scalar(select(func.count()).select_from(Message))

    second = api_client.post("/integrations/telegram/sync")
    assert second.status_code == 200
    assert second.json()["messages_created"] == 0
    assert second.json()["messages_existing"] == created
    assert db_session.scalar(select(func.count()).select_from(Message)) == first_count


def test_telegram_sync_never_calls_ai(monkeypatch, api_client: TestClient) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("AI must not be called during Telegram sync")

    monkeypatch.setattr("app.ai.factory.get_ai_provider", boom)
    response = api_client.post("/integrations/telegram/sync")
    assert response.status_code == 200


def test_factory_default_is_mock() -> None:
    assert isinstance(get_telegram_adapter(), MockTelegramAdapter)


def test_private_group_channel_mapping() -> None:
    private = map_dialog(sample_private_dialog())
    group = map_dialog(sample_group_dialog())
    channel = map_dialog(sample_channel_dialog())
    super_group = map_dialog(sample_supergroup_dialog())
    assert private.external_id == "user:2002"
    assert private.chat_type == ChatType.DIRECT
    assert private.name == "Eduard"
    assert group.external_id == "chat:3003"
    assert group.chat_type == ChatType.GROUP
    assert channel.external_id == "channel:4004"
    assert channel.chat_type == ChatType.CHANNEL
    assert super_group.external_id == "channel:5005"
    assert super_group.chat_type == ChatType.GROUP
    assert canonical_peer_id("user", 2002) != canonical_peer_id("chat", 2002)
    assert canonical_peer_id("chat", 2002) != canonical_peer_id("channel", 2002)


def test_incoming_and_outgoing_mapping() -> None:
    incoming = map_message(incoming_private(), current_user_id=1001)
    outgoing = map_message(outgoing_private(), current_user_id=1001)
    assert incoming is not None
    assert incoming.is_outgoing is False
    assert incoming.sender_id == "user:2002"
    assert incoming.timestamp.tzinfo is not None
    assert incoming.timestamp.utcoffset() == timezone.utc.utcoffset(incoming.timestamp)
    assert incoming.raw_data is None
    assert outgoing is not None
    assert outgoing.is_outgoing is True
    assert outgoing.sender_id == "user:1001"
    assert outgoing.attach_contact is False


def test_native_out_beats_missing_sender() -> None:
    record = TelegramMessageRecord(
        message_id=3,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(11),
        out=False,
        sender_kind=None,
        sender_id=None,
        text="no sender metadata",
    )
    mapped = map_message(record, current_user_id=1001)
    assert mapped is not None
    assert mapped.is_outgoing is False
    assert mapped.sender_id is None


def test_unknown_direction_skipped() -> None:
    record = TelegramMessageRecord(
        message_id=4,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(11),
        out=None,
        sender_kind="user",
        sender_id=9999,
        text="unclear",
    )
    assert map_message(record, current_user_id=1001) is None


def test_media_placeholder_and_caption() -> None:
    photo = TelegramMessageRecord(
        message_id=5,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(12),
        out=False,
        sender_kind="user",
        sender_id=2002,
        media_kind="photo",
    )
    captioned = TelegramMessageRecord(
        message_id=6,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(12, 1),
        out=False,
        sender_kind="user",
        sender_id=2002,
        text="look",
        media_kind="photo",
    )
    mapped_photo = map_message(photo, current_user_id=1001)
    mapped_caption = map_message(captioned, current_user_id=1001)
    assert mapped_photo is not None and mapped_photo.text == "[Photo]"
    assert mapped_caption is not None and mapped_caption.text == "look"


def test_service_message_skipped() -> None:
    record = TelegramMessageRecord(
        message_id=7,
        chat_external_id="chat:3003",
        chat_name="Buyers",
        chat_type=ChatType.GROUP,
        date=ts(13),
        out=False,
        is_service=True,
        text="user joined",
    )
    assert map_message(record, current_user_id=1001) is None


def test_channel_post_no_person_contact(db_session: Session) -> None:
    dialog = sample_channel_dialog()
    post = TelegramMessageRecord(
        message_id=8,
        chat_external_id="channel:4004",
        chat_name="Offers",
        chat_type=ChatType.CHANNEL,
        date=ts(14),
        out=False,
        sender_kind="channel",
        sender_id=4004,
        sender_name="Offers",
        text="New geo live",
    )
    reader = FakeTelegramReadClient(dialogs=[dialog], messages={"channel:4004": [post]})
    adapter = TelegramAdapter(reader, chat_limit=20, message_limit=50)
    result = asyncio.run(sync_telegram_messages(db_session, adapter, chat_limit=20, message_limit=50))
    db_session.commit()
    assert result.messages_created == 1
    stored = db_session.scalar(select(Message))
    assert stored is not None
    assert stored.sender_external_id == "channel:4004"
    assert stored.contact_id is None
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 0


def test_outgoing_self_does_not_create_telegram_contact(db_session: Session) -> None:
    dialog = sample_private_dialog()
    reader = FakeTelegramReadClient(
        dialogs=[dialog],
        messages={"user:2002": [outgoing_private()]},
    )
    adapter = TelegramAdapter(reader, chat_limit=20, message_limit=50)
    asyncio.run(sync_telegram_messages(db_session, adapter, chat_limit=20, message_limit=50))
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1
    assert db_session.scalar(select(Message)).is_outgoing is True


def test_same_telegram_sender_reused_across_chats(db_session: Session) -> None:
    private = sample_private_dialog()
    group = sample_group_dialog()
    from_eduard_private = incoming_private()
    from_eduard_group = TelegramMessageRecord(
        message_id=21,
        chat_external_id="chat:3003",
        chat_name="Buyers",
        chat_type=ChatType.GROUP,
        date=ts(15),
        out=False,
        sender_kind="user",
        sender_id=2002,
        sender_name="Eduard",
        text="in group",
    )
    reader = FakeTelegramReadClient(
        dialogs=[private, group],
        messages={
            "user:2002": [from_eduard_private],
            "chat:3003": [from_eduard_group],
        },
    )
    adapter = TelegramAdapter(reader, chat_limit=20, message_limit=50)
    asyncio.run(sync_telegram_messages(db_session, adapter, chat_limit=20, message_limit=50))
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 1
    assert db_session.scalar(select(func.count()).select_from(ContactIdentity)) == 1
    identity = db_session.scalar(select(ContactIdentity))
    assert identity is not None
    assert identity.platform == Platform.TELEGRAM
    assert identity.external_user_id == "user:2002"


def test_telegram_does_not_merge_typex_contact(db_session: Session) -> None:
    from app.schemas.unified import UnifiedMessage
    from app.services.message_ingestion import MessageIngestionService

    service = MessageIngestionService(db_session)
    service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="tx-1",
            chat_id="tx-eduard",
            chat_name="Eduard",
            sender_id="user:2002",
            sender_name="Eduard",
            text="typex hello",
            timestamp=ts(9),
        )
    )
    dialog = sample_private_dialog()
    reader = FakeTelegramReadClient(dialogs=[dialog], messages={"user:2002": [incoming_private()]})
    adapter = TelegramAdapter(reader, chat_limit=20, message_limit=50)
    asyncio.run(sync_telegram_messages(db_session, adapter, chat_limit=20, message_limit=50))
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 2
    platforms = {row.platform for row in db_session.scalars(select(ContactIdentity)).all()}
    assert platforms == {Platform.TYPEX, Platform.TELEGRAM}


def test_naive_timestamp_normalized_to_utc() -> None:
    record = TelegramMessageRecord(
        message_id=9,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=datetime(2026, 8, 17, 16, 0, 0),
        out=False,
        sender_kind="user",
        sender_id=2002,
        text="naive",
    )
    mapped = map_message(record, current_user_id=1001)
    assert mapped is not None
    assert mapped.timestamp.tzinfo is not None
    assert mapped.timestamp.tzinfo == timezone.utc


def test_messages_ingested_chronologically(db_session: Session) -> None:
    newer = TelegramMessageRecord(
        message_id=32,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(18),
        out=False,
        sender_kind="user",
        sender_id=2002,
        text="later",
    )
    older = TelegramMessageRecord(
        message_id=31,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(17),
        out=False,
        sender_kind="user",
        sender_id=2002,
        text="earlier",
    )
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [newer, older]},
    )
    adapter = TelegramAdapter(reader, chat_limit=20, message_limit=50)
    asyncio.run(sync_telegram_messages(db_session, adapter, chat_limit=20, message_limit=50))
    db_session.commit()
    texts = [row.text for row in db_session.scalars(select(Message).order_by(Message.timestamp)).all()]
    assert texts == ["earlier", "later"]


def test_duplicate_sync_is_idempotent(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [incoming_private(), outgoing_private()]},
    )
    first = asyncio.run(
        sync_telegram_messages(
            db_session,
            TelegramAdapter(reader, chat_limit=20, message_limit=50),
            chat_limit=20,
            message_limit=50,
        )
    )
    db_session.commit()
    second = asyncio.run(
        sync_telegram_messages(
            db_session,
            TelegramAdapter(
                FakeTelegramReadClient(
                    dialogs=[sample_private_dialog()],
                    messages={"user:2002": [incoming_private(), outgoing_private()]},
                ),
                chat_limit=20,
                message_limit=50,
            ),
            chat_limit=20,
            message_limit=50,
        )
    )
    db_session.commit()
    assert first.messages_created == 2
    assert second.messages_created == 0
    assert second.messages_existing == 2
    assert db_session.scalar(select(func.count()).select_from(Chat)) == 1
    assert db_session.scalar(select(func.count()).select_from(Message)) == 2


def test_rate_limit_error_is_safe(monkeypatch, api_client: TestClient) -> None:
    adapter = TelegramAdapter(
        FakeTelegramReadClient(list_error=TelegramRateLimitError("Telegram rate limit reached")),
        chat_limit=20,
        message_limit=50,
    )
    monkeypatch.setattr("app.api.telegram.get_telegram_adapter", lambda: adapter)
    monkeypatch.setattr(
        "app.api.telegram.get_settings",
        lambda: SimpleNamespace(
            telegram_mode="real",
            telegram_api_id=1,
            telegram_api_hash="hash",
            telegram_session_path="data/telegram.session",
            telegram_sync_chat_limit=20,
            telegram_sync_message_limit=50,
        ),
    )
    response = api_client.post("/integrations/telegram/sync")
    assert response.status_code == 429
    assert response.json()["detail"] == "Telegram rate limit reached"
    assert "flood" not in response.json()["detail"].lower()


def test_authorization_error_is_safe(monkeypatch, api_client: TestClient) -> None:
    adapter = TelegramAdapter(
        FakeTelegramReadClient(authorized=False),
        chat_limit=20,
        message_limit=50,
    )
    monkeypatch.setattr("app.api.telegram.get_telegram_adapter", lambda: adapter)
    monkeypatch.setattr(
        "app.api.telegram.get_settings",
        lambda: SimpleNamespace(
            telegram_mode="real",
            telegram_api_id=1,
            telegram_api_hash="hash",
            telegram_session_path="data/telegram.session",
            telegram_sync_chat_limit=20,
            telegram_sync_message_limit=50,
        ),
    )
    response = api_client.post("/integrations/telegram/sync")
    assert response.status_code == 401
    assert response.json()["detail"] == "Telegram authorization required"


def test_configuration_missing(monkeypatch, api_client: TestClient) -> None:
    monkeypatch.setattr(
        "app.api.telegram.get_settings",
        lambda: SimpleNamespace(
            telegram_mode="real",
            telegram_api_id=None,
            telegram_api_hash=None,
            telegram_session_path="data/telegram.session",
            telegram_sync_chat_limit=20,
            telegram_sync_message_limit=50,
        ),
    )
    health = api_client.get("/integrations/telegram/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["configured"] is False
    assert payload["sync_ready"] is False
    assert "TELEGRAM_API_ID" in payload["missing_configuration"]
    assert "TELEGRAM_API_HASH" in payload["missing_configuration"]
    sync = api_client.post("/integrations/telegram/sync")
    assert sync.status_code == 400
    assert sync.json()["detail"] == "Telegram configuration required"


def test_adapter_and_reader_have_no_write_methods() -> None:
    adapter_methods = _public_methods(TelegramAdapter)
    reader_methods = _public_methods(TelethonReadClient)
    assert adapter_methods.isdisjoint(FORBIDDEN_ADAPTER_METHODS)
    assert reader_methods.isdisjoint(FORBIDDEN_ADAPTER_METHODS)
    assert "send_message" not in adapter_methods
    assert "get_chats" in adapter_methods
    assert "list_dialogs" in reader_methods
    assert "get_messages" in reader_methods


def test_sync_uses_only_read_wrapper_operations(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [incoming_private()]},
    )
    adapter = TelegramAdapter(reader, chat_limit=20, message_limit=50)
    asyncio.run(sync_telegram_messages(db_session, adapter, chat_limit=20, message_limit=50))
    assert "list_dialogs" in reader.calls
    assert any(item.startswith("get_messages:") for item in reader.calls)
    assert "get_me" in reader.calls
    write_ops = {"send_message", "send_file", "edit_message", "delete_messages", "forward_messages"}
    assert write_ops.isdisjoint(set(reader.calls))


def test_auth_cli_does_not_read_chats() -> None:
    import app.integrations.telegram_auth as auth_mod

    source = inspect.getsource(auth_mod)
    assert "list_dialogs" not in source
    assert "iter_messages" not in source
    assert "get_messages" not in source
    assert "iter_dialogs" not in source


def test_public_errors_hide_secrets() -> None:
    from app.integrations.telegram_errors import public_telegram_message

    assert public_telegram_message(TelegramConfigurationError("api_hash=abc phone=+1")) == (
        "Telegram configuration required"
    )
    assert "abc" not in public_telegram_message(TelegramAuthorizationError("session /tmp/secret"))
