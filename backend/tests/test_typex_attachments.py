import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import AttachmentKind, ChatType, MessageDirection, Platform
from app.integrations.typex_errors import TypeXToolUnavailableError
from app.integrations.typex_files import map_downloadable_file
from app.integrations.typex_policy import is_allowed_local_save_tool, is_write_tool
from app.media_placeholder import detect_media_placeholder
from app.models import Chat, Message, MessageAttachment
from app.schemas.unified import UnifiedAttachment, UnifiedMessage
from app.services.attachment_storage import attachments_root, resolve_storage_key
from app.services.inbox import message_preview
from app.services.message_ingestion import MessageIngestionService
from app.services.typex_chat_identity import merge_typex_duplicate_messages
from app.services.typex_sync import sync_typex_messages
from tests.typex_helpers import (
    TEST_UPLOAD_TOOL,
    TYPEX_DOWNLOAD_CHAT_FILE,
    TYPEX_LIST_DOWNLOADABLE_FILES,
    TYPEX_LIST_FOLDER_FEEDS,
    TYPEX_SEARCH_CHAT_RECORDS,
    TYPEX_SEARCH_CONTACT,
    TYPEX_SEND_MESSAGE,
    mcp_client,
    rpc_result,
    session_handler,
    tool_payload,
    typex_adapter,
)


def _ts() -> datetime:
    return datetime(2026, 8, 17, 10, tzinfo=timezone.utc)


def test_list_downloadable_is_read_and_save_is_local_only() -> None:
    assert is_write_tool(TYPEX_LIST_DOWNLOADABLE_FILES) is False
    assert is_write_tool(TYPEX_DOWNLOAD_CHAT_FILE) is True
    assert is_allowed_local_save_tool(TYPEX_DOWNLOAD_CHAT_FILE) is True
    assert is_write_tool(TEST_UPLOAD_TOOL) is True
    assert is_allowed_local_save_tool(TEST_UPLOAD_TOOL) is False
    assert is_write_tool(TYPEX_SEND_MESSAGE) is True


def test_download_denied_without_local_save_grant() -> None:
    handler = session_handler(
        [TYPEX_DOWNLOAD_CHAT_FILE],
        call_results={TYPEX_DOWNLOAD_CHAT_FILE.name: {}},
    )
    client = mcp_client(handler, allowed={TYPEX_DOWNLOAD_CHAT_FILE.name})
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool(TYPEX_DOWNLOAD_CHAT_FILE.name, {"opaque_ref": "ref"}))


def test_upload_denied_even_with_local_save_grant() -> None:
    calls: dict[str, list[dict]] = {}
    handler = session_handler([TEST_UPLOAD_TOOL], calls=calls, default_call_result={})
    client = mcp_client(handler, allowed={TEST_UPLOAD_TOOL.name}, local_save={TEST_UPLOAD_TOOL.name})
    with pytest.raises(TypeXToolUnavailableError):
        asyncio.run(client.call_tool(TEST_UPLOAD_TOOL.name, {"target": "x", "file_path": "a.png"}))
    assert calls == {}


def test_map_downloadable_image_and_file() -> None:
    image = map_downloadable_file(
        {"file_ref": "f-1", "message_ref": "msg-1", "file_name": "shot.png", "kind": "image"}
    )
    other = map_downloadable_file(
        {"file_ref": "f-2", "message_ref": "msg-2", "file_name": "offer.pdf", "kind": "file"}
    )
    assert image is not None
    assert image.kind is AttachmentKind.IMAGE
    assert other is not None
    assert other.kind is AttachmentKind.FILE
    assert map_downloadable_file({"file_name": "no-ref.png"}) is None


def test_ingest_attachment_and_serve_file(
    db_session: Session,
    api_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    stored = attachments_root() / "typex" / "chat" / "file.png"
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
    service = MessageIngestionService(db_session)
    message, created = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id="msg-1",
            chat_id="txc:direct:Partner",
            chat_name="Partner",
            sender_name="John",
            text="see screenshot",
            timestamp=_ts(),
            direction=MessageDirection.UNKNOWN,
            attachments=[
                UnifiedAttachment(
                    file_ref="session-ref",
                    filename="shot.png",
                    kind=AttachmentKind.IMAGE,
                    message_external_id="msg-1",
                    content_type="image/png",
                    storage_key="typex/chat/file.png",
                    byte_size=stored.stat().st_size,
                )
            ],
        )
    )
    db_session.commit()
    assert created is True
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 1
    payload = api_client.get(f"/chats/{message.chat_id}/messages").json()
    assert payload[0]["attachments"][0]["kind"] == "image"
    url = payload[0]["attachments"][0]["url"]
    assert url.endswith("/file")
    response = api_client.get(url.removeprefix("/api"))
    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_media_placeholder_recovers_kind_count_and_caption() -> None:
    bare = detect_media_placeholder("发送了图片")
    assert bare is not None
    assert bare.kind is AttachmentKind.IMAGE
    assert bare.count == 1
    assert bare.caption is None

    captioned = detect_media_placeholder('发送了 1 张图片，并且说了"И тут что "')
    assert captioned is not None
    assert captioned.kind is AttachmentKind.IMAGE
    assert captioned.count == 1
    assert captioned.caption == "И тут что"

    many = detect_media_placeholder('发送了 3 张图片，并且说了"смотри отчет"')
    assert many is not None
    assert many.count == 3

    voice = detect_media_placeholder("发送了语音")
    assert voice is not None
    assert voice.kind is AttachmentKind.VOICE

    file_stub = detect_media_placeholder("[Document]")
    assert file_stub is not None
    assert file_stub.kind is AttachmentKind.FILE

    assert detect_media_placeholder("要哪個地區的 lol") is None
    assert detect_media_placeholder("") is None
    assert detect_media_placeholder(None) is None


def test_chat_preview_replaces_media_stub() -> None:
    assert message_preview('发送了 1 张图片，并且说了"И тут что "') == "[Image] И тут что"
    assert message_preview("发送了图片") == "[Image]"
    assert message_preview("要哪個地區的 lol") == "要哪個地區的 lol"


def test_placeholder_exposes_caption_and_marks_missing_media(
    db_session: Session,
    api_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    stored = attachments_root() / "typex" / "chat" / "file.png"
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
    service = MessageIngestionService(db_session)
    base = {
        "platform": Platform.TYPEX,
        "chat_id": "txc:direct:Partner",
        "chat_name": "Partner",
        "sender_name": "John",
        "direction": MessageDirection.INCOMING,
    }
    service.ingest_message(
        UnifiedMessage(
            **base,
            external_id="msg-placeholder",
            text='发送了 2 张图片，并且说了"И тут что "',
            timestamp=_ts(),
        )
    )
    message, _created = service.ingest_message(
        UnifiedMessage(
            **base,
            external_id="msg-with-file",
            text="发送了图片",
            timestamp=datetime(2026, 8, 17, 11, tzinfo=timezone.utc),
            attachments=[
                UnifiedAttachment(
                    file_ref="session-ref",
                    filename="shot.png",
                    kind=AttachmentKind.IMAGE,
                    content_type="image/png",
                    storage_key="typex/chat/file.png",
                    byte_size=stored.stat().st_size,
                )
            ],
        )
    )
    db_session.commit()
    payload = api_client.get(f"/chats/{message.chat_id}/messages").json()
    by_id = {item["external_id"]: item for item in payload}
    assert by_id["msg-placeholder"]["media_placeholder"] == {
        "kind": "image",
        "count": 2,
        "caption": "И тут что",
    }
    assert by_id["msg-with-file"]["media_placeholder"]["caption"] is None
    assert len(by_id["msg-with-file"]["attachments"]) == 1


def _download_handler(
    tools,
    calls,
    list_result,
    message_text: str = "hello",
    download_ok: bool = True,
):
    inner = session_handler(
        tools,
        calls=calls,
        call_results={
            TYPEX_LIST_FOLDER_FEEDS.name: [
                {"opaque_ref": "feed-1", "name": "Affiliate John", "type": "direct"}
            ],
            TYPEX_SEARCH_CHAT_RECORDS.name: [
                {
                    "message_ref": "msg-1",
                    "send_name": "John",
                    "content": message_text,
                    "send_time": "2026-08-17T10:00:00Z",
                }
            ],
            TYPEX_LIST_DOWNLOADABLE_FILES.name: {
                "ok": True,
                "chat_name": "Affiliate John",
                "file_count": len(list_result),
                "files": list_result,
                "summary": "listed",
            },
            TYPEX_DOWNLOAD_CHAT_FILE.name: {"ok": True},
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if (
            body.get("method") != "tools/call"
            or body.get("params", {}).get("name") != TYPEX_DOWNLOAD_CHAT_FILE.name
        ):
            return inner(request)
        inner(request)
        arguments = body["params"].get("arguments") or {}
        save_path = arguments.get("save_path")
        if not download_ok or not isinstance(save_path, str) or not save_path:
            return httpx.Response(200, json=rpc_result(body["id"], tool_payload({"ok": False})))
        folder = Path(save_path)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "image_1.jpg"
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 12)
        return httpx.Response(
            200,
            json=rpc_result(
                body["id"],
                tool_payload({"ok": True, "file_name": target.name, "saved_path": str(target)}),
            ),
        )

    return handler


def _sync_adapter(handler):
    return typex_adapter(
        handler,
        chats_tool=TYPEX_LIST_FOLDER_FEEDS.name,
        messages_tool=TYPEX_SEARCH_CHAT_RECORDS.name,
        current_user_tool=None,
        files_list_tool=TYPEX_LIST_DOWNLOADABLE_FILES.name,
        file_save_tool=TYPEX_DOWNLOAD_CHAT_FILE.name,
    )


SYNC_TOOLS = [
    TYPEX_LIST_FOLDER_FEEDS,
    TYPEX_SEARCH_CHAT_RECORDS,
    TYPEX_SEARCH_CONTACT,
    TYPEX_LIST_DOWNLOADABLE_FILES,
    TYPEX_DOWNLOAD_CHAT_FILE,
    TYPEX_SEND_MESSAGE,
]


def test_sync_saves_chat_file_and_does_not_send(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    calls: dict[str, list[dict]] = {}
    handler = _download_handler(
        SYNC_TOOLS,
        calls,
        [
            {
                "file_ref": "file-1",
                "message_ref": "msg-1",
                "file_name": "shot.png",
                "kind": "image",
            }
        ],
    )
    adapter = _sync_adapter(handler)
    result = asyncio.run(sync_typex_messages(db_session, adapter, chat_limit=2, message_limit=5))
    db_session.commit()
    assert result.files_seen == 1
    assert result.files_saved == 1
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 1
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1
    listed = calls[TYPEX_LIST_DOWNLOADABLE_FILES.name][0]
    assert listed["opaque_ref"] == "feed-1"
    assert "query" not in listed
    saved = calls[TYPEX_DOWNLOAD_CHAT_FILE.name][0]
    assert saved["opaque_ref"] == "feed-1"
    assert saved["file_ref"] == "file-1"
    assert "save_path" in saved
    assert TYPEX_SEND_MESSAGE.name not in calls


def test_resync_with_rotated_file_ref_keeps_one_attachment(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    listed = [
        {
            "file_ref": "session-a-1",
            "message_ref": "msg-1",
            "file_name": "shot.png",
            "kind": "image",
        }
    ]
    handler = _download_handler(SYNC_TOOLS, {}, listed)
    asyncio.run(sync_typex_messages(db_session, _sync_adapter(handler), chat_limit=2, message_limit=5))
    db_session.commit()
    listed[0]["file_ref"] = "session-b-1"
    asyncio.run(sync_typex_messages(db_session, _sync_adapter(handler), chat_limit=2, message_limit=5))
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 1


def test_sync_downloads_media_by_message_ref_when_list_is_empty(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    calls: dict[str, list[dict]] = {}
    handler = _download_handler(SYNC_TOOLS, calls, [], message_text="发送了图片")
    result = asyncio.run(
        sync_typex_messages(db_session, _sync_adapter(handler), chat_limit=2, message_limit=5)
    )
    db_session.commit()
    assert result.files_seen == 0
    assert result.files_saved == 1
    assert result.media_without_file == 0
    saved = calls[TYPEX_DOWNLOAD_CHAT_FILE.name][0]
    assert saved["message_ref"] == "msg-1"
    assert "file_ref" not in saved
    attachment = db_session.scalars(select(MessageAttachment)).one()
    assert attachment.kind is AttachmentKind.IMAGE
    assert attachment.filename == "image_1.png"
    assert attachment.content_type == "image/png"
    assert resolve_storage_key(attachment.storage_key) is not None

    repeated = asyncio.run(
        sync_typex_messages(db_session, _sync_adapter(handler), chat_limit=2, message_limit=5)
    )
    db_session.commit()
    assert repeated.files_saved == 0
    assert len(calls[TYPEX_DOWNLOAD_CHAT_FILE.name]) == 1
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 1


def test_sync_counts_media_when_download_fails(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    handler = _download_handler(
        SYNC_TOOLS, {}, [], message_text="发送了图片", download_ok=False
    )
    result = asyncio.run(
        sync_typex_messages(db_session, _sync_adapter(handler), chat_limit=2, message_limit=5)
    )
    db_session.commit()
    assert result.files_saved == 0
    assert result.media_without_file == 1
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 0


def test_merge_moves_attachments_to_kept_message(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    chat = Chat(
        platform=Platform.TYPEX,
        external_id="txc:direct:Partner",
        name="Partner",
        chat_type=ChatType.DIRECT,
    )
    db_session.add(chat)
    db_session.flush()
    kept = Message(
        chat_id=chat.id,
        external_id="ref-old",
        sender_name="John",
        text="see screenshot",
        timestamp=_ts(),
        direction=MessageDirection.INCOMING,
    )
    duplicate = Message(
        chat_id=chat.id,
        external_id="ref-new",
        sender_name="John",
        text="see screenshot",
        timestamp=_ts(),
        direction=MessageDirection.INCOMING,
    )
    db_session.add_all([kept, duplicate])
    db_session.flush()
    db_session.add(
        MessageAttachment(
            message_id=duplicate.id,
            kind=AttachmentKind.IMAGE,
            filename="shot.png",
            content_type="image/png",
            storage_key="typex/chat/shot.png",
            byte_size=16,
        )
    )
    db_session.flush()
    assert merge_typex_duplicate_messages(db_session) == 1
    db_session.commit()
    rows = list(db_session.scalars(select(MessageAttachment)))
    assert len(rows) == 1
    assert rows[0].message_id == kept.id
