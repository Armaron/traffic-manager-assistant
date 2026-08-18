"""Slack read-only integration tests. Never touch a live Slack workspace."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.enums import ChatType, DirectionSource, MessageDirection, Platform
from app.integrations.slack import SlackAdapter
from app.integrations.slack_client import (
    FORBIDDEN_METHODS,
    SlackSdkReadClient,
    assert_method_allowed,
    reset_slack_identity_cache,
)
from app.integrations.slack_errors import SlackAuthenticationError, SlackPermissionError
from app.integrations.slack_mapping import (
    SlackConversationRecord,
    SlackMessageRecord,
    chat_type_for,
    exact_ts,
    map_conversation,
    map_message,
    message_record_from_payload,
    slack_ts_to_datetime,
    thread_external_id_for,
)
from app.models import AIAnalysis, Chat, Message, MessageAttachment
from app.schemas.inbox import SlackSyncResult, TelegramSyncResult, TypeXSyncResult
from app.schemas.message import MessageRead
from app.schemas.unified import UnifiedMessage
from app.services.auto_sync import CYCLE_ORDER, AutoSyncScheduler
from app.services.message_ingestion import MessageIngestionService
from app.services.slack_events import SlackEventService
from app.services.slack_sync import sync_slack_messages
from app.services.sync_runtime import SyncPlatform, SyncRuntime, get_sync_runtime, reset_sync_runtime
from tests.slack_helpers import (
    PNG_BYTES,
    FakeSlackClient,
    RecordingTransport,
    incoming_message,
    sample_channel,
    sample_file,
    sample_im,
    sample_mpim,
    sample_private_channel,
)

WRITE_METHODS = [
    "chat.postMessage",
    "chat.update",
    "chat.delete",
    "files.upload",
    "files.getUploadURLExternal",
    "files.completeUploadExternal",
    "reactions.add",
    "conversations.create",
    "conversations.invite",
]


@pytest.fixture(autouse=True)
def _reset_slack_cache() -> None:
    reset_slack_identity_cache()
    yield
    reset_slack_identity_cache()


@pytest.fixture()
def _local_attachments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)


def _keep_open(session: Session) -> object:
    class Wrapper:
        def close(self) -> None:
            return None

        def __getattr__(self, name: str) -> object:
            return getattr(session, name)

    return Wrapper()


def _adapter(reader: FakeSlackClient, *, download: bool = True) -> SlackAdapter:
    return SlackAdapter(reader, chat_limit=10, message_limit=20, download_files=download)


def _sync(session: Session, reader: FakeSlackClient) -> SlackSyncResult:
    result = asyncio.run(
        sync_slack_messages(session, _adapter(reader), chat_limit=10, message_limit=20)
    )
    session.commit()
    return result


def test_slack_health_mock_hides_tokens(api_client: TestClient) -> None:
    response = api_client.get("/integrations/slack/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "mock"
    assert payload["configured"] is True
    assert payload["authenticated"] is True
    assert payload["sync_ready"] is True
    dumped = str(payload)
    assert "xoxp" not in dumped
    assert "xapp" not in dumped
    assert "token" not in dumped.lower()
    assert "user_id" not in payload


def test_missing_tokens_configured_false(monkeypatch: pytest.MonkeyPatch, api_client: TestClient) -> None:
    settings = Settings(slack_mode="real", slack_user_token=None, slack_app_token=None)
    monkeypatch.setattr("app.api.slack.get_settings", lambda: settings)
    response = api_client.get("/integrations/slack/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["authenticated"] is False
    assert payload["sync_ready"] is False


def test_invalid_auth_is_safe() -> None:
    reader = FakeSlackClient(auth_error=SlackAuthenticationError("Slack authentication failed"))
    with pytest.raises(SlackAuthenticationError, match="Slack authentication failed"):
        asyncio.run(_adapter(reader).ensure_ready_for_sync())


def test_auth_test_extracts_self_id() -> None:
    identity = asyncio.run(FakeSlackClient().auth_test())
    assert identity.user_id == "U_SELF"


def test_token_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    client = SlackSdkReadClient(RecordingTransport(), user_token="xoxp-secret-token-value")
    with caplog.at_level(logging.INFO):
        asyncio.run(client.auth_test())
    assert "xoxp-secret-token-value" not in caplog.text


def test_channel_mapping() -> None:
    chat = map_conversation(
        SlackConversationRecord(id="C111", display_name="#offers", is_channel=True)
    )
    assert chat.platform is Platform.SLACK
    assert chat.chat_type is ChatType.CHANNEL
    assert chat.name == "#offers"


def test_private_channel_mapping() -> None:
    chat = map_conversation(
        SlackConversationRecord(id="G222", display_name="buyers-private", is_private=True)
    )
    assert chat.chat_type is ChatType.GROUP
    assert not chat.name.startswith("#")


def test_dm_mapping() -> None:
    chat = map_conversation(SlackConversationRecord(id="D333", display_name="Eduard", is_im=True))
    assert chat.chat_type is ChatType.DIRECT


def test_mpim_mapping() -> None:
    chat = map_conversation(SlackConversationRecord(id="G444", display_name="Eduard, Igor", is_mpim=True))
    assert chat.chat_type is ChatType.GROUP


def test_incoming_and_outgoing_direction() -> None:
    incoming = map_message(
        SlackMessageRecord(
            ts="1710000000.000100",
            channel_id="D333",
            chat_name="Eduard",
            chat_type=ChatType.DIRECT,
            user_id="U_OTHER",
            text="hello",
        ),
        current_user_id="U_SELF",
    )
    outgoing = map_message(
        SlackMessageRecord(
            ts="1710000001.000200",
            channel_id="D333",
            chat_name="Eduard",
            chat_type=ChatType.DIRECT,
            user_id="U_SELF",
            text="hi",
        ),
        current_user_id="U_SELF",
    )
    unknown = map_message(
        SlackMessageRecord(
            ts="1710000002.000300",
            channel_id="D333",
            chat_name="Eduard",
            chat_type=ChatType.DIRECT,
            text="system",
        ),
        current_user_id="U_SELF",
    )
    assert incoming is not None and incoming.direction is MessageDirection.INCOMING
    assert outgoing is not None and outgoing.direction is MessageDirection.OUTGOING
    assert outgoing.direction_source is DirectionSource.NATIVE
    assert unknown is not None and unknown.direction is MessageDirection.UNKNOWN
    assert outgoing.direction_source is not DirectionSource.PROFILE_NAME


def test_timestamp_order_and_exact_ts() -> None:
    ts = "1710000000.000123"
    assert exact_ts(ts) == ts
    assert exact_ts(1710000000.000123) is None
    assert slack_ts_to_datetime("1710000000.000100") < slack_ts_to_datetime("1710000001.000200")
    mapped = map_message(
        SlackMessageRecord(
            ts=ts,
            channel_id="D333",
            chat_name="Eduard",
            chat_type=ChatType.DIRECT,
            user_id="U_OTHER",
            text="hello",
        ),
        current_user_id="U_SELF",
    )
    assert mapped is not None
    assert mapped.external_id == ts


def test_thread_root_and_reply() -> None:
    root = map_message(
        SlackMessageRecord(
            ts="1710000100.000001",
            channel_id="C111",
            chat_name="#offers",
            chat_type=ChatType.CHANNEL,
            user_id="U_OTHER",
            text="root",
        ),
        current_user_id="U_SELF",
    )
    reply = map_message(
        SlackMessageRecord(
            ts="1710000101.000002",
            channel_id="C111",
            chat_name="#offers",
            chat_type=ChatType.CHANNEL,
            user_id="U_OTHER",
            text="reply",
            thread_ts="1710000100.000001",
        ),
        current_user_id="U_SELF",
    )
    assert root is not None and root.thread_external_id is None
    assert reply is not None and reply.thread_external_id == "1710000100.000001"
    assert thread_external_id_for("1710000100.000001", "1710000100.000001") is None


def test_thread_stored_and_duplicate_reply(db_session: Session) -> None:
    reader = FakeSlackClient(
        conversations=[sample_channel()],
        history={"C111": [incoming_message(ts="1710000100.000001", text="root", reply_count=1)]},
        replies={
            "C111:1710000100.000001": [
                incoming_message(ts="1710000100.000001", text="root"),
                incoming_message(ts="1710000101.000002", text="reply", thread_ts="1710000100.000001"),
            ]
        },
    )
    _sync(db_session, reader)
    rows = list(db_session.scalars(select(Message)).all())
    assert any(item.thread_external_id == "1710000100.000001" for item in rows)
    _sync(db_session, reader)
    assert db_session.scalar(select(func.count()).select_from(Message)) == len(rows)


def test_typex_telegram_thread_field_stays_null(db_session: Session) -> None:
    service = MessageIngestionService(db_session)
    stamp = slack_ts_to_datetime("1710000000.000100")
    service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="tx-1",
            chat_id="tx-chat",
            chat_name="TypeX",
            text="hello",
            timestamp=stamp,
            direction=MessageDirection.INCOMING,
        )
    )
    service.ingest_message(
        UnifiedMessage(
            platform=Platform.TELEGRAM,
            external_id="11",
            chat_id="user:1",
            chat_name="Eduard",
            text="hi",
            timestamp=stamp,
            direction=MessageDirection.INCOMING,
        )
    )
    db_session.commit()
    assert all(row.thread_external_id is None for row in db_session.scalars(select(Message)).all())


def test_adapter_lists_chat_types() -> None:
    reader = FakeSlackClient(
        conversations=[sample_channel(), sample_private_channel(), sample_im(), sample_mpim()],
        history={"C111": [], "G222": [], "D333": [], "G444": []},
    )
    chats = asyncio.run(_adapter(reader).get_chats())
    types = {item.external_id: item.chat_type for item in chats}
    names = {item.external_id: item.name for item in chats}
    assert types["C111"] is ChatType.CHANNEL
    assert names["C111"].startswith("#")
    assert types["G222"] is ChatType.GROUP
    assert types["D333"] is ChatType.DIRECT
    assert names["D333"] == "Eduard"
    assert types["G444"] is ChatType.GROUP


@pytest.mark.usefixtures("_local_attachments")
def test_image_download_sniff_and_no_private_url(db_session: Session, api_client: TestClient) -> None:
    file_info = sample_file(name="photo.jpg", mime="image/jpeg")
    from io import BytesIO
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (64, 48), (12, 90, 200)).save(buffer, format="PNG")
    png = buffer.getvalue()
    reader = FakeSlackClient(
        conversations=[sample_im()],
        history={"D333": [incoming_message(files=[file_info], text="")]},
        files={"F1": file_info},
        file_bytes={"F1": png},
    )
    _sync(db_session, reader)
    attachment = db_session.scalars(select(MessageAttachment)).one()
    assert attachment.kind.value == "image"
    assert attachment.content_type == "image/png"
    message = db_session.get(Message, attachment.message_id)
    assert message is not None
    dumped = str(MessageRead.model_validate(message).model_dump())
    assert "files.slack.com" not in dumped
    assert "url_private" not in dumped
    response = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/file")
    assert response.status_code == 200
    thumb = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail")
    assert thumb.status_code == 200


@pytest.mark.usefixtures("_local_attachments")
def test_metadata_oversize_skips_download(db_session: Session) -> None:
    huge = sample_file(file_id="F2", size=26 * 1024 * 1024)
    reader = FakeSlackClient(
        conversations=[sample_im()],
        history={"D333": [incoming_message(files=[huge], text="")]},
        files={"F2": huge},
        file_bytes={"F2": PNG_BYTES},
    )
    result = _sync(db_session, reader)
    assert result.files_skipped >= 1
    assert reader.download_calls == []


@pytest.mark.usefixtures("_local_attachments")
def test_actual_oversize_discarded(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import attachment_storage

    monkeypatch.setattr(attachment_storage, "MAX_ATTACHMENT_BYTES", 10)
    monkeypatch.setattr("app.integrations.slack.MAX_ATTACHMENT_BYTES", 10)
    info = sample_file(file_id="F3", size=8)
    reader = FakeSlackClient(
        conversations=[sample_im()],
        history={"D333": [incoming_message(files=[info], text="")]},
        files={"F3": info},
        file_bytes={"F3": PNG_BYTES},
    )
    result = _sync(db_session, reader)
    assert result.files_downloaded == 0
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 0


@pytest.mark.usefixtures("_local_attachments")
def test_repeat_sync_does_not_redownload(db_session: Session) -> None:
    info = sample_file()
    reader = FakeSlackClient(
        conversations=[sample_im()],
        history={"D333": [incoming_message(files=[info], text="shot")]},
        files={"F1": info},
        file_bytes={"F1": PNG_BYTES},
    )
    _sync(db_session, reader)
    _sync(db_session, reader)
    assert reader.download_calls == ["F1"]
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 1


def test_allowlist_rejects_write_methods() -> None:
    transport = RecordingTransport()
    client = SlackSdkReadClient(transport, user_token="xoxp-test")
    for method in WRITE_METHODS + sorted(FORBIDDEN_METHODS):
        with pytest.raises(SlackPermissionError):
            assert_method_allowed(method)
        with pytest.raises(SlackPermissionError):
            asyncio.run(client._call(method))
    assert transport.calls == []


def test_slack_adapter_has_no_write_methods() -> None:
    names = {name for name in dir(SlackAdapter) if not name.startswith("_")}
    forbidden = {
        "send_message",
        "post_message",
        "postMessage",
        "upload_file",
        "add_reaction",
        "invite",
        "create_channel",
    }
    assert names.isdisjoint(forbidden)


def test_mock_sync_and_health(api_client: TestClient, db_session: Session) -> None:
    first = api_client.post("/integrations/slack/sync")
    assert first.status_code == 200
    assert first.json()["messages_created"] >= 1
    second = api_client.post("/integrations/slack/sync")
    assert second.json()["messages_created"] == 0
    assert db_session.scalars(select(Chat).where(Chat.platform == Platform.SLACK)).first()


def test_slack_sync_never_calls_ai(monkeypatch: pytest.MonkeyPatch, api_client: TestClient) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("AI must not run")

    monkeypatch.setattr("app.services.analysis.AIAnalysisService.analyze_message", boom)
    assert api_client.post("/integrations/slack/sync").status_code == 200


def test_slack_not_in_history_poll_cycle() -> None:
    assert CYCLE_ORDER == (SyncPlatform.TYPEX, SyncPlatform.TELEGRAM)
    assert SyncPlatform.SLACK not in CYCLE_ORDER


def test_typex_and_telegram_auto_sync_still_run() -> None:
    settings = Settings(
        auto_sync_enabled=True,
        auto_sync_interval_seconds=30,
        auto_sync_startup_delay_seconds=0.0,
        auto_sync_platform_timeout_seconds=5,
    )
    runtime = SyncRuntime.from_settings(settings)
    calls: list[str] = []

    class Dummy:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    async def typex(_session: object) -> object:
        calls.append("typex")
        return TypeXSyncResult(messages_created=1)

    async def telegram(_session: object) -> object:
        calls.append("telegram")
        return TelegramSyncResult(messages_created=1)

    async def slack(_session: object) -> object:
        calls.append("slack")
        return SlackSyncResult(messages_created=1)

    scheduler = AutoSyncScheduler(
        runtime,
        settings=settings,
        session_factory=Dummy,
        runners={
            SyncPlatform.TYPEX: typex,
            SyncPlatform.TELEGRAM: telegram,
            SyncPlatform.SLACK: slack,
        },
        readiness={
            SyncPlatform.TYPEX: lambda: (True, None),
            SyncPlatform.TELEGRAM: lambda: (True, None),
            SyncPlatform.SLACK: lambda: (True, None),
        },
    )
    asyncio.run(scheduler.run_cycle())
    assert calls == ["typex", "telegram"]


@pytest.mark.usefixtures("_local_attachments")
def test_socket_ack_ingest_duplicate_and_generation(db_session: Session) -> None:
    reset_sync_runtime()
    runtime = get_sync_runtime()
    runtime.set_auto_sync_enabled(True)
    reader = FakeSlackClient(conversations=[sample_im()], history={"D333": []})
    adapter = _adapter(reader)
    asyncio.run(adapter.ensure_ready_for_sync())
    acks: list[str] = []
    started = 0

    async def ack() -> None:
        acks.append("ok")

    async def connect(service: SlackEventService) -> None:
        nonlocal started
        started += 1
        service._set_connected(True)

    service = SlackEventService(
        settings=Settings(
            slack_mode="real",
            slack_user_token="xoxp-test",
            slack_app_token="xapp-test",
            auto_sync_enabled=True,
        ),
        adapter_factory=lambda: adapter,
        connect_fn=connect,
        session_factory=lambda: _keep_open(db_session),
    )

    async def scenario() -> int:
        await service.start()
        await service.start()
        envelope = {"event": incoming_message(ts="1710000900.000900", text="live ping")}
        await service.handle_envelope("env-1", envelope, ack)
        await service._queue.join()
        generation = runtime.inbox_generation
        await service.handle_envelope("env-1", envelope, ack)
        await service._queue.join()
        await service.handle_envelope("bad", {"hello": True}, ack)
        await service.stop()
        return generation

    generation = asyncio.run(scenario())
    assert started == 1
    assert len(acks) >= 3
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1
    assert runtime.inbox_generation == generation
    stored = db_session.scalars(select(Message)).one()
    assert stored.direction is MessageDirection.INCOMING
    assert stored.external_id == "1710000900.000900"


@pytest.mark.usefixtures("_local_attachments")
def test_socket_worker_recovers_after_db_error(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_sync_runtime()
    get_sync_runtime().set_auto_sync_enabled(True)
    reader = FakeSlackClient(conversations=[sample_im()])
    adapter = _adapter(reader)
    asyncio.run(adapter.ensure_ready_for_sync())
    calls = {"n": 0}
    from app.services import slack_events as slack_events_mod
    original = slack_events_mod.ingest_slack_event_message

    async def flaky(session: Session, target: SlackAdapter, payload: dict, **kwargs: object):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db boom")
        return await original(session, target, payload, **kwargs)

    monkeypatch.setattr(slack_events_mod, "ingest_slack_event_message", flaky)
    service = SlackEventService(
        settings=Settings(slack_mode="mock", auto_sync_enabled=True),
        adapter_factory=lambda: adapter,
        session_factory=lambda: _keep_open(db_session),
    )

    async def scenario() -> None:
        await service.start()

        async def ack() -> None:
            return None

        await service.handle_envelope("a", {"event": incoming_message(ts="1710000910.000001", text="one")}, ack)
        await asyncio.sleep(0.05)
        await service.handle_envelope("b", {"event": incoming_message(ts="1710000910.000002", text="two")}, ack)
        await service._queue.join()
        await service.stop()

    asyncio.run(scenario())
    texts = {item.text for item in db_session.scalars(select(Message)).all()}
    assert "two" in texts



def test_auto_sync_off_pauses_persistence(db_session: Session) -> None:
    reset_sync_runtime()
    get_sync_runtime().set_auto_sync_enabled(False)
    reader = FakeSlackClient(conversations=[sample_im()])
    adapter = _adapter(reader)
    asyncio.run(adapter.ensure_ready_for_sync())
    service = SlackEventService(
        settings=Settings(slack_mode="mock"),
        adapter_factory=lambda: adapter,
        session_factory=lambda: _keep_open(db_session),
    )

    async def scenario() -> None:
        await service.start()

        async def ack() -> None:
            return None

        await service.handle_envelope(
            "x",
            {"event": incoming_message(ts="1710000920.000001", text="paused")},
            ack,
        )
        await service._queue.join()
        await service.stop()

    asyncio.run(scenario())
    assert db_session.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.usefixtures("_local_attachments")
def test_manual_sync_works_while_auto_off(db_session: Session) -> None:
    reset_sync_runtime()
    get_sync_runtime().set_auto_sync_enabled(False)
    reader = FakeSlackClient(
        conversations=[sample_im()],
        history={"D333": [incoming_message(text="manual")]},
    )
    assert _sync(db_session, reader).messages_created == 1


def test_turning_auto_sync_on_schedules_one_recon(monkeypatch: pytest.MonkeyPatch, api_client: TestClient) -> None:
    calls: list[str] = []

    async def fake_recon(*, reason: str) -> None:
        calls.append(reason)

    monkeypatch.setattr("app.api.sync.run_one_slack_reconciliation", fake_recon)
    assert api_client.post("/integrations/sync/auto", json={"enabled": False}).status_code == 200
    assert api_client.post("/integrations/sync/auto", json={"enabled": True}).status_code == 200
    assert calls == ["auto_sync_on"]


def test_slack_message_makes_analysis_stale(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.mock_provider import MockAIProvider
    from app.services.analysis import AIAnalysisService
    from app.services.inbox import analysis_staleness

    reader = FakeSlackClient(
        conversations=[sample_im()],
        history={"D333": [incoming_message(ts="1710000930.000001", text="first")]},
    )
    _sync(db_session, reader)
    message = db_session.scalars(select(Message)).one()
    analysis = asyncio.run(AIAnalysisService(db_session, MockAIProvider()).analyze_message(message.id))
    db_session.commit()
    called = {"n": 0}
    original = MockAIProvider.analyze_message

    async def wrapped(self: MockAIProvider, *args: object, **kwargs: object) -> object:
        called["n"] += 1
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(MockAIProvider, "analyze_message", wrapped)
    reader.history["D333"] = [
        incoming_message(ts="1710000930.000001", text="first"),
        incoming_message(ts="1710000930.000002", text="second"),
    ]
    _sync(db_session, reader)
    stale = analysis_staleness(db_session, analysis)
    assert stale.is_stale is True
    assert called["n"] == 0
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 1


def test_analyze_slack_chat_uses_existing_service(db_session: Session, api_client: TestClient) -> None:
    reader = FakeSlackClient(
        conversations=[sample_im()],
        history={"D333": [incoming_message(text="Need a higher CPA for KR")]},
    )
    _sync(db_session, reader)
    chat = db_session.scalars(select(Chat).where(Chat.platform == Platform.SLACK)).one()
    response = api_client.post(f"/chats/{chat.id}/analyze")
    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_explanation_ru"]
    assert payload["draft_reply"]


def test_mentions_and_chat_type_helpers() -> None:
    assert chat_type_for(SlackConversationRecord(id="C", display_name="#x", is_channel=True)) is ChatType.CHANNEL
    record = message_record_from_payload(
        {"ts": "1.0", "user": "U1", "text": "hi <@U_SELF>", "files": []},
        channel_id="C",
        chat_name="#x",
        chat_type=ChatType.CHANNEL,
        users={"U_SELF": "Operator"},
    )
    assert "hi" in (record.text or "")

