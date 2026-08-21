from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import AttachmentKind, ChatType, ConversationStatus, DirectionSource, MessageDirection, Platform
from app.models import AIAnalysis, Chat, Message, MessageAttachment
from app.enums import AnalysisCategory, Priority
from app.services.sync_runtime import get_sync_runtime


def _chat(session: Session, *, platform: Platform, external_id: str, name: str) -> Chat:
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


def _msg(session: Session, chat: Chat, *, external_id: str, text: str) -> Message:
    from app.time_utils import utc_now

    message = Message(
        chat_id=chat.id,
        external_id=external_id,
        sender_name="Partner",
        text=text,
        timestamp=utc_now(),
        direction=MessageDirection.INCOMING,
        direction_source=DirectionSource.NATIVE,
    )
    session.add(message)
    session.flush()
    return message


def test_clear_slack_deletes_only_slack_chats_and_messages(
    api_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    slack = _chat(db_session, platform=Platform.SLACK, external_id="C1", name="Slack Room")
    telegram = _chat(db_session, platform=Platform.TELEGRAM, external_id="T1", name="Telegram Pal")
    typex = _chat(db_session, platform=Platform.TYPEX, external_id="X1", name="TypeX Lead")
    slack_msg = _msg(db_session, slack, external_id="m1", text="Can you do CPA $20?")
    _msg(db_session, telegram, external_id="m2", text="Telegram stays")
    _msg(db_session, typex, external_id="m3", text="TypeX stays")
    db_session.add(
        AIAnalysis(
            message_id=slack_msg.id,
            summary="s",
            request="r",
            category=AnalysisCategory.OTHER,
            priority=Priority.NORMAL,
            needs_reply=True,
            needs_igor=False,
            reason="reason",
            provider="mock",
            model="mock",
        )
    )
    db_session.commit()
    called = {"adapter": 0}

    def boom(*_args, **_kwargs):
        called["adapter"] += 1
        raise AssertionError("clear must not call Slack")

    monkeypatch.setattr("app.api.slack.get_slack_adapter", boom)
    before = get_sync_runtime().inbox_generation
    response = api_client.post("/integrations/slack/clear")
    assert response.status_code == 200
    assert response.json() == {"chats_deleted": 1, "messages_deleted": 1}
    assert called["adapter"] == 0
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(Chat).where(Chat.platform == Platform.SLACK)) == 0
    assert db_session.scalar(select(func.count()).select_from(Chat).where(Chat.id == telegram.id)) == 1
    assert db_session.scalar(select(func.count()).select_from(Chat).where(Chat.id == typex.id)) == 1
    assert db_session.scalar(select(func.count()).select_from(Message).where(Message.chat_id == telegram.id)) == 1
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 0
    assert get_sync_runtime().inbox_generation == before + 1


def test_clear_slack_removes_orphan_attachment_files(
    api_client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.services.thumbnails.attachments_root", lambda: tmp_path / "attachments")
    attachments = tmp_path / "attachments"
    attachments.mkdir(parents=True)
    stored = attachments / "slack-file.bin"
    stored.write_bytes(b"secret")
    chat = _chat(db_session, platform=Platform.SLACK, external_id="C2", name="Files")
    message = _msg(db_session, chat, external_id="f1", text="invoice")
    db_session.add(
        MessageAttachment(
            message_id=message.id,
            kind=AttachmentKind.FILE,
            filename="invoice.pdf",
            storage_key="slack-file.bin",
            byte_size=6,
        )
    )
    db_session.commit()
    response = api_client.post("/integrations/slack/clear")
    assert response.status_code == 200
    assert response.json()["chats_deleted"] == 1
    db_session.expire_all()
    assert not stored.exists()
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 0


def test_clear_slack_empty_is_ok(api_client: TestClient) -> None:
    response = api_client.post("/integrations/slack/clear")
    assert response.status_code == 200
    assert response.json() == {"chats_deleted": 0, "messages_deleted": 0}
